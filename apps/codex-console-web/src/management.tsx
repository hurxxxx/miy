import { Button, Input } from '@mty/ui';
import { useEffect, useState } from 'react';
import { api, apiBasePath, type Task } from './api';
import type { components } from './api.generated';
import { statusCopy, type Copy, type Translate } from './i18n';

type Agent = components['schemas']['AgentOut'];
export type Service = components['schemas']['ServiceOut'];
export type Purpose = 'development' | 'inspection' | 'deployment' | 'recovery';
export type TaskDraft = {
  purpose: Purpose;
  service_id?: string;
  title: string;
  text: string;
};
const terminal = new Set(['completed', 'interrupted', 'errored', 'shutdown']);

export function needsAttention(task: Task) {
  return (
    !!task.pending_count ||
    ['waiting', 'failed', 'uncertain'].includes(task.status) ||
    task.agents?.some(
      (a) =>
        !!a.flags?.length ||
        ['errored', 'systemError', 'notFound'].includes(a.status),
    )
  );
}
export function running(task: Task) {
  return (
    ['starting', 'running', 'waiting'].includes(task.status) ||
    task.agents?.some((a) => a.parent_thread_id && !terminal.has(a.status))
  );
}
export function taskRank(task: Task) {
  return needsAttention(task) ? 0 : running(task) ? 1 : !task.thread_id ? 2 : 3;
}
export function sortTasks(tasks: Task[]) {
  return [...tasks].sort(
    (a, b) =>
      Number(!!b.pinned) - Number(!!a.pinned) ||
      taskRank(a) - taskRank(b) ||
      b.updated_at.localeCompare(a.updated_at) ||
      a.id.localeCompare(b.id),
  );
}

export function useOverview(enabled: boolean, changed: () => void) {
  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource(`${apiBasePath}/overview/events`);
    source.addEventListener('changed', changed);
    // SSE cursors only invalidate persisted projections; reconnect also reloads.
    source.onopen = changed;
    const interval = window.setInterval(changed, 10000);
    const visible = () => {
      if (document.visibilityState === 'visible') changed();
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      source.close();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [enabled, changed]);
}

function agentStatus(agent: Agent): Copy {
  if (agent.flags?.includes('waitingOnApproval')) return 'Approval needed';
  if (agent.flags?.includes('waitingOnUserInput'))
    return 'Waiting for your response';
  return (
    (
      {
        active: 'Running',
        running: 'Running',
        pendingInit: 'Starting',
        idle: 'Ready',
        notLoaded: 'Not loaded',
        completed: 'Completed',
        interrupted: 'Interrupted',
        errored: 'Failed',
        systemError: 'Needs recovery',
        shutdown: 'Stopped',
        notFound: 'Unknown',
      } as Record<string, Copy>
    )[agent.status] ?? 'Unknown'
  );
}
function activity(value: string | null | undefined, t: Translate) {
  const labels: Record<string, Copy> = {
    command: 'Running a command',
    files: 'Editing files',
    search: 'Searching',
    delegating: 'Delegating work',
  };
  return value ? (labels[value] ? t(labels[value]) : value) : '';
}

export function AgentTree({ agents, t }: { agents: Agent[]; t: Translate }) {
  if (!agents.length)
    return <p className="muted">{t('No agent activity yet')}</p>;
  const ids = new Set(agents.map((a) => a.thread_id));
  const branch = (
    parent: string | null,
    visited: Set<string>,
  ): React.ReactNode =>
    agents
      .filter((a) =>
        parent
          ? a.parent_thread_id === parent
          : !a.parent_thread_id || !ids.has(a.parent_thread_id),
      )
      .filter((a) => !visited.has(a.thread_id))
      .map((a) => (
        <li key={a.thread_id}>
          <details className="agent-card">
            <summary>
              <strong>{a.name}</strong> {a.role && <span>{a.role}</span>}{' '}
              <span className="status-badge">{t(agentStatus(a))}</span>
            </summary>
            <p>{activity(a.activity, t) || t('No current step reported')}</p>
            {Array.isArray(a.progress?.steps) && (
              <ol>
                {(a.progress.steps as { step: string; status: string }[]).map(
                  (s, i) => (
                    <li key={i}>
                      {s.status === 'completed'
                        ? '✓ '
                        : s.status === 'inProgress'
                          ? '→ '
                          : ''}
                      {s.step}
                    </li>
                  ),
                )}
              </ol>
            )}
            <small>
              {t('Checked')}: {new Date(a.updated_at).toLocaleString()}
            </small>
          </details>
          <ul>{branch(a.thread_id, new Set([...visited, a.thread_id]))}</ul>
        </li>
      ));
  return <ul className="agent-tree">{branch(null, new Set())}</ul>;
}

export function ManagementView({
  view,
  t,
  tasks,
  openTask,
  draft,
  refresh,
  onError,
  newTask,
}: {
  view: 'services' | 'tasks';
  t: Translate;
  tasks: Task[];
  openTask: (id: string) => void;
  draft: (value: TaskDraft) => void;
  refresh: () => Promise<void>;
  onError: (e: unknown) => void;
  newTask: () => void;
}) {
  const [services, setServices] = useState<Service[]>([]);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState('all');
  const [environment, setEnvironment] = useState('all');
  const [purpose, setPurpose] = useState('all');
  const [query, setQuery] = useState('');
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const result = await api<Service[]>('/monitor/services');
        if (!cancelled) {
          setServices(result);
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);
  const request = (service: Service, purpose: Purpose) => {
    const goal = t(
      purpose === 'deployment'
        ? 'Prepare a deployment'
        : purpose === 'recovery'
          ? 'Investigate recovery'
          : 'Inspect this service',
    );
    draft({
      purpose,
      service_id: service.id,
      title: `${service.name} · ${goal}`,
      text: `${service.name} (${service.environment}): ${goal}. ${t('Inspect the repository instructions and current state, then explain the proposed action and required approvals.')}`,
    });
  };
  const environments = [
    ...new Set(
      tasks.map((x) => String(x.context?.environment ?? '')).filter(Boolean),
    ),
  ];
  const visible = sortTasks(
    tasks.filter(
      (task) =>
        (!query ||
          task.title.toLocaleLowerCase().includes(query.toLocaleLowerCase())) &&
        (filter === 'all' || taskRank(task) === Number(filter)) &&
        (environment === 'all' || task.context?.environment === environment) &&
        (purpose === 'all' ||
          (task.context?.purpose ?? 'development') === purpose),
    ),
  );
  return (
    <main className="management-view">
      <h1>{t(view === 'services' ? 'Service status' : 'Work overview')}</h1>
      <Button onClick={newTask}>{t('New task')}</Button>
      <p className="muted">
        {t(
          'Codex investigates and operates. This console displays status and your requests.',
        )}
      </p>
      {view === 'services' ? (
        <>
          {failed && <p role="alert">{t('Monitoring is unavailable')}</p>}
          <div className="service-grid">
            {services.map((service) => (
              <article className="service-card" key={service.id}>
                <h2>{service.name}</h2>
                <small>{service.environment}</small>
                <p className="status-badge">
                  {t(
                    (
                      {
                        healthy: 'Healthy',
                        running: 'Running',
                        stopped: 'Stopped',
                        unavailable: 'Unavailable',
                        unknown: 'Unknown',
                      } as Record<string, Copy>
                    )[failed ? 'unknown' : service.status] ?? 'Unknown',
                  )}
                </p>
                {service.version && (
                  <p>
                    {t('Version')}: {service.version}
                  </p>
                )}
                <p>
                  {t('Checked')}:{' '}
                  {service.checked_at
                    ? new Date(service.checked_at).toLocaleString()
                    : t('Unknown')}
                  {service.stale || failed
                    ? ` · ${t('Stale observation')}`
                    : ''}
                </p>
                <div className="management-actions">
                  <Button onClick={() => request(service, 'inspection')}>
                    {t('Ask Codex to inspect')}
                  </Button>
                  <Button onClick={() => request(service, 'deployment')}>
                    {t('Ask Codex to deploy')}
                  </Button>
                  <Button onClick={() => request(service, 'recovery')}>
                    {t('Ask Codex to recover')}
                  </Button>
                </div>
              </article>
            ))}
          </div>
          <details className="recovery-guide">
            <summary>{t('Recover the Codex session service')}</summary>
            <p>
              {t(
                'Open Codex in the source repository on the server and paste this request.',
              )}
            </p>
            <textarea
              readOnly
              aria-label={t('Recovery request')}
              value={t(
                'Read AGENTS.md and the Codex Console owner documentation. Inspect the independently supervised management and session services. Diagnose the session connection failure, preserve existing conversations and running work, and propose recovery. Ask before restarting or deploying. Verify the public login, task state, and agent activity after the approved recovery.',
              )}
            />
          </details>
        </>
      ) : (
        <>
          {(failed ||
            services.some(
              (s) =>
                s.id === 'console-session' &&
                (s.stale || !['healthy', 'running'].includes(s.status)),
            )) && (
            <p role="status">
              {t(
                'Session service unavailable. Showing the last reported task state.',
              )}
            </p>
          )}
          <div className="management-filters">
            <Input
              aria-label={t('Search tasks')}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('Search tasks')}
            />
            <select
              aria-label={t('Status filter')}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              {(
                [
                  'All tasks',
                  'Needs attention',
                  'Running',
                  'Not started',
                  'Recent results',
                ] as Copy[]
              ).map((label, i) => (
                <option key={label} value={i ? String(i - 1) : 'all'}>
                  {t(label)}
                </option>
              ))}
            </select>
            <select
              aria-label={t('Environment filter')}
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
            >
              <option value="all">{t('All environments')}</option>
              {environments.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
            <select
              aria-label={t('Purpose filter')}
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            >
              <option value="all">{t('All purposes')}</option>
              {(
                ['development', 'inspection', 'deployment', 'recovery'] as const
              ).map((x) => (
                <option key={x} value={x}>
                  {t(
                    (
                      {
                        development: 'Development',
                        inspection: 'Inspection',
                        deployment: 'Deployment',
                        recovery: 'Recovery',
                      } as const
                    )[x],
                  )}
                </option>
              ))}
            </select>
          </div>
          {visible.map((task) => (
            <article key={task.id} className="overview-task">
              <div className="management-actions">
                <h2>
                  <button onClick={() => openTask(task.id)}>
                    {task.title}
                  </button>
                </h2>
                <Button
                  aria-pressed={!!task.pinned}
                  onClick={() =>
                    void api(
                      `/overview/${task.id}`,
                      { pinned: !task.pinned },
                      'PATCH',
                    )
                      .then(refresh)
                      .catch(onError)
                  }
                >
                  {t(task.pinned ? 'Unpin' : 'Pin')}
                </Button>
              </div>
              <p>
                {String(task.context?.environment ?? '')} ·{' '}
                {task.pending_count
                  ? `${t('Needs attention')} (${task.pending_count})`
                  : t(running(task) ? 'Running' : statusCopy(task.status))}{' '}
                · {t('Active agents')}:{' '}
                {
                  (task.agents ?? []).filter((a) =>
                    ['active', 'running', 'pendingInit'].includes(a.status),
                  ).length
                }
              </p>
              <small>
                {t('Checked')}: {new Date(task.updated_at).toLocaleString()}
              </small>
              <p>
                {Array.isArray(task.progress?.steps)
                  ? (
                      task.progress.steps as { step: string; status: string }[]
                    ).find((s) => s.status === 'inProgress')?.step
                  : ''}
              </p>
              <AgentTree agents={task.agents ?? []} t={t} />
            </article>
          ))}
          {!visible.length && <p>{t('No matching tasks')}</p>}
        </>
      )}
    </main>
  );
}
