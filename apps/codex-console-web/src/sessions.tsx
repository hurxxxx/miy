import { Button, Input } from '@miy/ui';
import {
  ArrowUpRight,
  Folder,
  MessagesSquare,
  Pin,
  PinOff,
  Plus,
} from 'lucide-react';
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MutableRefObject,
} from 'react';
import { EmptyState, PageLayout } from './page-layout';
import { api, record, string, type Task } from './api';
import type { components } from './api.generated';
import {
  activityGroup,
  currentStep,
  executing,
  executionCount,
  hasFinished,
  needsAttention,
  rowStatus,
} from './agent-state';
import { AgentTree, useServices } from './management';
import { useTaskSearch } from './task-search';
import type { Copy, Translate } from './i18n';

export function sortSessions(tasks: Task[]) {
  return [...tasks].sort(
    (a, b) =>
      Number(!!b.pinned) - Number(!!a.pinned) ||
      b.updated_at.localeCompare(a.updated_at) ||
      a.id.localeCompare(b.id),
  );
}

export type SessionFilters = {
  status: 'all' | 'running' | 'attention' | 'finished';
  source: 'all' | 'session' | 'templates';
  query: string;
};
const filters: { id: SessionFilters['status']; label: Copy }[] = [
  { id: 'all', label: 'All sessions' },
  { id: 'running', label: 'Running' },
  { id: 'attention', label: 'Needs attention' },
  { id: 'finished', label: 'Finished' },
];

export function SessionsView({
  tasks,
  t,
  checkedAt,
  failed,
  filters: selected,
  onFilters,
  openTask,
  openTemplates,
  refresh,
  onError,
  templateId = null,
  clearTemplate,
  importSession,
  newTask,
  selectedTask = null,
  scrollPosition,
}: {
  tasks: Task[];
  t: Translate;
  checkedAt: number | null;
  failed: boolean;
  filters: SessionFilters;
  onFilters: (filters: SessionFilters) => void;
  openTask: (id: string) => void;
  openTemplates: () => void;
  refresh: () => Promise<void>;
  onError: (error: unknown) => void;
  templateId?: string | null;
  clearTemplate?: () => void;
  importSession: () => void;
  newTask: () => void;
  selectedTask?: string | null;
  scrollPosition?: MutableRefObject<number>;
}) {
  const { services, failed: servicesFailed } = useServices();
  const source = templateId ? 'templates' : selected.source;
  const runtimeUnavailable =
    servicesFailed ||
    services.some(
      (service) =>
        ((source !== 'templates' && service.id === 'console-session') ||
          (source !== 'session' && service.id === 'console-templates')) &&
        (service.stale || !['healthy', 'running'].includes(service.status)),
    );
  const [retry, setRetry] = useState(0);
  const [template, setTemplate] = useState<
    components['schemas']['TemplateOut'] | null
  >(null);
  const [templateFailed, setTemplateFailed] = useState(false);
  useEffect(() => {
    setTemplate(null);
    setTemplateFailed(false);
    if (!templateId) return;
    const controller = new AbortController();
    void api<components['schemas']['TemplateOut']>(
      `/templates/${encodeURIComponent(templateId)}`,
      undefined,
      'GET',
      controller.signal,
    )
      .then((row) => {
        if (!controller.signal.aborted) setTemplate(row);
      })
      .catch(() => {
        if (!controller.signal.aborted) setTemplateFailed(true);
      });
    return () => controller.abort();
  }, [templateId, retry]);
  const query = selected.query.trim();
  const {
    remote,
    key: searchKey,
    search,
  } = useTaskSearch(tasks, query, templateId, retry);
  const rows = (
    remote ? (search.key === searchKey ? search.rows : []) : tasks
  ).filter((task) => source === 'all' || task.executor === source);
  const matches = {
    all: () => true,
    running: executing,
    attention: needsAttention,
    finished: hasFinished,
  };
  const counts = Object.fromEntries(
    filters.map(({ id }) => [id, rows.filter(matches[id]).length]),
  );
  const visible = sortSessions(rows.filter(matches[selected.status]));
  const loading = remote
    ? search.key !== searchKey || search.loading
    : !checkedAt && !failed;
  const unavailable = remote
    ? search.key === searchKey && search.failed
    : failed;
  const lastChecked = remote
    ? search.key === searchKey
      ? search.checkedAt
      : null
    : checkedAt;
  const filtered =
    !!query ||
    selected.status !== 'all' ||
    (!templateId && selected.source !== 'all');
  const viewport = useRef<HTMLElement>(null);
  const restoreScroll = useRef(true);
  useLayoutEffect(() => {
    if (loading || !restoreScroll.current || !viewport.current) return;
    viewport.current.scrollTop = scrollPosition?.current ?? 0;
    restoreScroll.current = false;
  }, [
    loading,
    visible.length,
    scrollPosition,
    selected.query,
    selected.status,
    selected.source,
  ]);
  const changeFilters = (next: SessionFilters) => {
    if (
      next.query === selected.query &&
      next.status === selected.status &&
      next.source === selected.source
    )
      return;
    if (scrollPosition) scrollPosition.current = 0;
    restoreScroll.current = true;
    onFilters(next);
  };
  return (
    <PageLayout
      className="sessions-view"
      scrollRef={viewport}
      onScroll={(event) => {
        if (scrollPosition && !restoreScroll.current)
          scrollPosition.current = event.currentTarget.scrollTop;
      }}
      title={t(templateId ? 'Template run history' : 'Sessions')}
      description={t(
        'Find conversations, follow running work, and respond to requests.',
      )}
      actions={
        <>
          <Button variant="ghost" size="comfortable" onClick={importSession}>
            {t('Import Codex session')}
          </Button>
          <Button variant="primary" size="comfortable" onClick={newTask}>
            <Plus size={16} aria-hidden="true" />
            {t('New task')}
          </Button>
        </>
      }
    >
      {templateId && (
        <div
          className="template-history-scope"
          role="region"
          aria-label={t('Selected template')}
        >
          <div>
            <strong>
              {template?.id === templateId
                ? template.definition.name
                : t('Task template')}
            </strong>
            {template?.id === templateId && template.archived && (
              <span className="status-badge">{t('Archived template')}</span>
            )}
            <p className="muted">
              {t(
                'Runs from every version of this template. Each run keeps its original settings.',
              )}
            </p>
          </div>
          <Button size="comfortable" onClick={clearTemplate}>
            {t('All sessions')}
          </Button>
        </div>
      )}
      {templateId && templateFailed && (
        <div className="agent-list-warning" role="status">
          <p>
            {t(
              'Template details are unavailable. The history filter is still applied.',
            )}
          </p>
          <Button onClick={() => setRetry((value) => value + 1)}>
            {t('Retry')}
          </Button>
        </div>
      )}
      <div
        className="agent-status-filters"
        role="group"
        aria-label={t('Status filter')}
      >
        {filters.map(({ id, label }) => (
          <button
            key={id}
            aria-pressed={selected.status === id}
            onClick={() => changeFilters({ ...selected, status: id })}
          >
            <span>{t(label)}</span>
            <strong>{loading && !lastChecked ? '…' : counts[id]}</strong>
          </button>
        ))}
      </div>
      <div className="list-controls">
        <div className="agent-list-toolbar list-toolbar">
          <Input
            type="search"
            aria-label={t('Search sessions')}
            placeholder={t('Search sessions')}
            maxLength={200}
            value={selected.query}
            onChange={(event) =>
              changeFilters({ ...selected, query: event.target.value })
            }
          />
          {!templateId && (
            <select
              aria-label={t('Task source')}
              value={selected.source}
              onChange={(event) =>
                changeFilters({
                  ...selected,
                  source: event.target.value as SessionFilters['source'],
                })
              }
            >
              <option value="all">{t('All sources')}</option>
              <option value="session">{t('Task workspace')}</option>
              <option value="templates">{t('Template runs')}</option>
            </select>
          )}
        </div>
        <div className="agent-list-meta">
          <p role="status">
            {loading
              ? t('Searching')
              : `${t('Matching tasks')}: ${visible.length}`}{' '}
            · {t('Last reported running agents')}:{' '}
            {rows.reduce((sum, task) => sum + executionCount(task), 0)}
          </p>
          {lastChecked && (
            <small>
              {t('List refreshed')}:{' '}
              {new Date(lastChecked).toLocaleTimeString()}
            </small>
          )}
        </div>
      </div>
      {unavailable && (
        <div className="agent-list-warning" role="status">
          <p>
            {t(
              'Session list could not be refreshed. Showing the last received state.',
            )}
          </p>
          <Button
            onClick={() =>
              remote
                ? setRetry((value) => value + 1)
                : void refresh().catch(onError)
            }
          >
            {t('Retry')}
          </Button>
        </div>
      )}
      {runtimeUnavailable && (
        <p className="agent-list-warning" role="status">
          {t(
            'An execution service is unavailable. Showing the last reported agent state.',
          )}
        </p>
      )}
      {visible.length > 0 && (
        <div className="agent-columns list-columns" aria-hidden="true">
          <span>{t('Status')}</span>
          <span>{t('Task')}</span>
          <span>{t('Updated')}</span>
          <span>{t('Actions')}</span>
        </div>
      )}
      <ul
        className="session-list"
        aria-label={t('Sessions')}
        aria-busy={loading}
      >
        {visible.map((task) => (
          <li key={task.id}>
            <SessionRun
              task={task}
              selected={task.id === selectedTask}
              t={t}
              openTask={openTask}
              refresh={refresh}
              onError={onError}
            />
          </li>
        ))}
      </ul>
      {!visible.length && !loading && !unavailable && (
        <EmptyState
          icon={<MessagesSquare size={28} />}
          title={t(
            templateId && !filtered
              ? 'No runs from this template yet'
              : filtered
                ? 'No matching sessions'
                : 'No sessions yet',
          )}
          description={t(
            templateId && !filtered
              ? 'Run this template to see agent status and results here.'
              : 'Choose another filter, or start a new task.',
          )}
          action={
            filtered ? (
              <Button
                size="comfortable"
                onClick={() =>
                  changeFilters({ status: 'all', source: 'all', query: '' })
                }
              >
                {t('Clear filters')}
              </Button>
            ) : (
              <Button
                size="comfortable"
                onClick={templateId ? openTemplates : newTask}
              >
                {t(templateId ? 'Task templates' : 'New task')}
              </Button>
            )
          }
        />
      )}
      <p className="page-footnote muted">
        {t('Recent work is shown here. Search by title to find older runs.')}
      </p>
    </PageLayout>
  );
}

function SessionRun({
  task,
  selected,
  t,
  openTask,
  refresh,
  onError,
}: {
  task: Task;
  selected: boolean;
  t: Translate;
  openTask: (id: string) => void;
  refresh: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const group = activityGroup(task);
  const [expanded, setExpanded] = useState(false);
  const [pinning, setPinning] = useState(false);
  return (
    <article
      className="overview-task agent-run"
      data-state={group ?? 'ready'}
      data-selected={selected}
    >
      <div className="agent-run-state">
        <span className="sr-only">{t('Status')}: </span>
        {t(group ? rowStatus(task, group) : 'Not started')}
      </div>
      <div className="agent-run-heading">
        <h2>
          <button
            className="session-title"
            aria-current={selected ? 'true' : undefined}
            onClick={() => openTask(task.id)}
          >
            {task.pinned && (
              <>
                <Pin size={12} aria-hidden="true" />
                <span className="sr-only">{t('Pinned')}</span>
              </>
            )}
            <span>{task.title}</span>
          </button>
        </h2>
        <p className="agent-run-path">
          <Folder size={13} aria-hidden="true" />
          <span className="sr-only">{t('Workspace')}</span>
          <code>{task.root}</code>
          {task.isolated && <span>{t('Isolated workspace')}</span>}
        </p>
        <div className="agent-run-meta">
          <span>
            {t(
              task.executor === 'templates' ? 'Template run' : 'Task workspace',
            )}
          </span>
          <span>
            {t('Agents')}: {task.agents.length}
          </span>
          {task.pending_count > 0 && (
            <span>
              {t('Pending requests')}: {task.pending_count}
            </span>
          )}
        </div>
        {executing(task) && (
          <p className="agent-run-step">
            <span>{t('Current step')}</span>
            {currentStep(task, t)}
          </p>
        )}
      </div>
      <time className="agent-run-updated" dateTime={task.updated_at}>
        <span className="sr-only">{t('Updated')}: </span>
        {new Date(task.updated_at).toLocaleString()}
      </time>
      <div className="agent-run-actions">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t(task.pinned ? 'Unpin' : 'Pin')}
          aria-pressed={!!task.pinned}
          disabled={pinning}
          onClick={() => {
            setPinning(true);
            void api(`/overview/${task.id}`, { pinned: !task.pinned }, 'PATCH')
              .then(refresh)
              .catch(onError)
              .finally(() => setPinning(false));
          }}
        >
          {task.pinned ? <PinOff size={16} /> : <Pin size={16} />}
        </Button>
        <Button variant="ghost" onClick={() => openTask(task.id)}>
          {t(
            task.pending_count
              ? 'Respond to requests'
              : 'Open conversation and results',
          )}
          <ArrowUpRight size={15} aria-hidden="true" />
        </Button>
      </div>
      {(task.agents.length > 0 || task.template_snapshot) && (
        <div className="agent-run-details">
          {task.agents.length > 0 && (
            <details
              className="agent-run-tree"
              open={expanded}
              onToggle={(event) => setExpanded(event.currentTarget.open)}
            >
              <summary>
                {t('Agent details')} <span>{task.agents.length}</span>
              </summary>
              <AgentTree agents={task.agents} t={t} />
            </details>
          )}
          {task.template_snapshot && (
            <details className="agent-run-settings">
              <summary>{t('Run settings')}</summary>
              <RunSettings snapshot={task.template_snapshot} t={t} />
            </details>
          )}
        </div>
      )}
    </article>
  );
}
function RunSettings({
  snapshot,
  t,
}: {
  snapshot: NonNullable<Task['template_snapshot']>;
  t: Translate;
}) {
  const definition = record(snapshot.definition);
  return (
    <>
      <dl className="run-settings">
        <dt>{t('Template name')}</dt>
        <dd>{string(definition.name)}</dd>
        <dt>{t('Template version')}</dt>
        <dd>{String(snapshot.version ?? '')}</dd>
        <dt>{t('Working directory relative to project')}</dt>
        <dd>{string(definition.directory)}</dd>
        <dt>{t('Execution mode')}</dt>
        <dd>{t(definition.stage === 'plan' ? 'Plan' : 'Implement')}</dd>
        <dt>{t('Permissions')}</dt>
        <dd>
          {t(
            definition.permissions === 'yolo'
              ? 'YOLO · Full access'
              : 'Ask when needed',
          )}
        </dd>
        <dt>{t('Model')}</dt>
        <dd>{string(definition.model) || t('Codex default')}</dd>
        <dt>{t('Available skills')}</dt>
        <dd>
          {Array.isArray(definition.skills)
            ? definition.skills.filter((x) => typeof x === 'string').join(', ')
            : '—'}
        </dd>
      </dl>
      <details>
        <summary>{t('Run inputs')}</summary>
        <dl className="run-settings">
          {Object.entries(record(snapshot.resolved_values)).map(
            ([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{string(value)}</dd>
              </div>
            ),
          )}
        </dl>
      </details>
      <details>
        <summary>{t('Saved request')}</summary>
        <p className="template-prompt">{string(snapshot.text)}</p>
      </details>
    </>
  );
}
