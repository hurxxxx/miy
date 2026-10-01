import { Button } from '@miy/ui';
import { useEffect, useState } from 'react';
import { api, apiBasePath, type Task } from './api';
import type { components } from './api.generated';
import { type Copy, type Translate } from './i18n';
import { PageLayout } from './page-layout';

import {
  activity,
  agentStatus,
  agentWorking,
  executing,
  needsAttention,
  sortTasks,
  type Agent,
} from './agent-state';
export type Service = components['schemas']['ServiceOut'];

export function useServices() {
  const [services, setServices] = useState<Service[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      void api<Service[]>(
        '/monitor/services',
        undefined,
        'GET',
        controller.signal,
      )
        .then((value) => {
          setServices(value);
          setFailed(false);
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true);
        });
    };
    load();
    const timer = window.setInterval(load, 10000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);
  return { services, failed };
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
  t,
  tasks,
  openTask,
  openTemplates,
}: {
  t: Translate;
  tasks: Task[];
  openTask: (id: string) => void;
  openTemplates: (request?: string) => void;
}) {
  const { services, failed } = useServices();
  const [host, setHost] = useState<components['schemas']['HostOut'] | null>(
    null,
  );
  const [hostFailed, setHostFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      void api<components['schemas']['HostOut']>(
        '/monitor/host',
        undefined,
        'GET',
        controller.signal,
      )
        .then((value) => {
          setHost(value);
          setHostFailed(false);
        })
        .catch(() => {
          if (!controller.signal.aborted) setHostFailed(true);
        });
    };
    load();
    const timer = window.setInterval(load, 10000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);
  const memory = host?.memory;
  const bytes = (n: number) =>
    `${(n / 1024 ** 3).toLocaleString(undefined, { maximumFractionDigits: 1 })} GiB`;
  const memoryTotal =
    memory?.cgroup_limit && memory.cgroup_limit < memory.total
      ? memory.cgroup_limit
      : memory?.total;
  const memoryUsed =
    memory?.cgroup_limit && memory.cgroup_limit < memory.total
      ? memory.cgroup_used
      : memory?.used;
  const unavailable =
    failed ||
    services.some(
      (s) =>
        s.id === 'console-session' &&
        (s.stale || !['healthy', 'running'].includes(s.status)),
    );
  return (
    <PageLayout
      className="monitoring-view"
      title={t('Monitoring')}
      description={t('Server observations and native Codex agent activity.')}
      actions={
        <Button size="comfortable" onClick={() => openTemplates()}>
          {t('Task templates')}
        </Button>
      }
    >
      <div className="monitor-summary">
        <div>
          <span>{t('Needs attention')}</span>
          <strong>{tasks.filter(needsAttention).length}</strong>
        </div>
        <div>
          <span>{t('Running')}</span>
          <strong>{tasks.filter(executing).length}</strong>
        </div>
        <div>
          <span>{t('Active agents')}</span>
          <strong>
            {
              new Set(
                tasks.flatMap((task) =>
                  (task.agents ?? [])
                    .filter(agentWorking)
                    .map((a) => a.thread_id),
                ),
              ).size
            }
          </strong>
        </div>
      </div>
      {unavailable && (
        <p className="monitor-notice" role="status">
          {t(
            'Session service unavailable. Showing the last reported task state.',
          )}
        </p>
      )}

      <>
        <section className="page-section">
          <h2>{t('Server resources')}</h2>
          {(hostFailed || host?.stale) && (
            <p role="status">{t('Stale observation')}</p>
          )}
          <table className="resource-table">
            <caption className="sr-only">{t('Server resources')}</caption>
            <thead>
              <tr>
                <th scope="col">{t('Resource')}</th>
                <th scope="col">{t('Usage')}</th>
                <th scope="col">{t('Details')}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">{t('Memory')}</th>
                <td>
                  {memory && memoryUsed != null && memoryTotal
                    ? `${bytes(memoryUsed)} / ${bytes(memoryTotal)}`
                    : t('Unknown')}
                </td>
                <td>
                  {memoryUsed != null && memoryTotal ? (
                    <meter
                      min={0}
                      max={memoryTotal}
                      high={memoryTotal * 0.85}
                      value={memoryUsed}
                      aria-label={t('Memory')}
                    />
                  ) : null}
                  {memory?.cgroup_limit && (
                    <small>
                      {t('Cgroup limit applied')}: {bytes(memory.cgroup_limit)}
                    </small>
                  )}
                </td>
              </tr>
              <tr>
                <th scope="row">{t('Swap')}</th>
                <td>
                  {memory
                    ? `${bytes(memory.swap_used)} / ${bytes(memory.swap_total)}`
                    : t('Unknown')}
                </td>
                <td>—</td>
              </tr>
              <tr>
                <th scope="row">{t('CPU load')}</th>
                <td>
                  {host?.load?.length
                    ? host.load.map((n) => n.toFixed(2)).join(' / ')
                    : t('Unknown')}
                </td>
                <td>
                  <small>{t('Load averages: 1, 5, 15 minutes')}</small>
                </td>
              </tr>
              {host?.disks?.map((d) => (
                <tr key={d.path}>
                  <th scope="row">
                    {t('Disk')} · {d.path}
                  </th>
                  <td>
                    {bytes(d.used)} / {bytes(d.total)}
                  </td>
                  <td>
                    <meter
                      min={0}
                      max={d.total}
                      high={d.total * 0.8}
                      value={d.used}
                      aria-label={`${t('Disk')} ${d.path}`}
                    />
                    <small>
                      {t('Available')}: {bytes(d.available)}
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <small>
            {t('Checked')}:{' '}
            {host?.checked_at
              ? new Date(host.checked_at).toLocaleString()
              : t('Unknown')}
          </small>
        </section>
        <section className="page-section">
          <h2>{t('Service status')}</h2>
          {failed && <p role="alert">{t('Monitoring is unavailable')}</p>}
          <div className="service-table">
            <div className="service-columns list-columns" aria-hidden="true">
              <span>{t('Service status')}</span>
              <span>{t('Status')}</span>
              <span>{t('Checked')}</span>
              <span>{t('Actions')}</span>
            </div>
            {services.map((service) => (
              <article key={service.id} className="service-line">
                <div>
                  <strong>{service.name}</strong>
                  <small>{service.environment}</small>
                </div>
                <span className="status-badge">
                  {t(
                    (
                      {
                        healthy: 'Healthy',
                        running: 'Running',
                        stopped: 'Stopped',
                        unavailable: 'Unavailable',
                        unknown: 'Unknown',
                      } as Record<string, Copy>
                    )[failed || service.stale ? 'unknown' : service.status] ??
                      'Unknown',
                  )}
                </span>
                <small className="service-checked">
                  {service.checked_at
                    ? new Date(service.checked_at).toLocaleString()
                    : t('Unknown')}
                  {service.stale || failed
                    ? ` · ${t('Stale observation')}`
                    : ''}
                </small>
                <Button onClick={() => openTemplates()}>
                  {t('Use a task template')}
                </Button>
              </article>
            ))}
          </div>
        </section>
        <section className="page-section">
          <h2>{t('Codex compatibility')}</h2>
          <dl className="version-list">
            <dt>{t('Installed CLI')}</dt>
            <dd>{host?.installed_cli ?? t('Unknown')}</dd>
            <dt>{t('Template runner CLI')}</dt>
            <dd>{host?.template_cli ?? t('Unknown')}</dd>
            <dt>{t('Console contract baseline')}</dt>
            <dd>{host?.contract_cli ?? t('Unknown')}</dd>
          </dl>
          <p className="muted">
            {t(
              'Version differences require protocol verification. Run the compatibility template when needed.',
            )}
          </p>
          <Button onClick={() => openTemplates()}>
            {t('Open update templates')}
          </Button>
        </section>
        <section className="page-section">
          <h2>{t('Agents')}</h2>
          {sortTasks(
            tasks.filter((task) => executing(task) || needsAttention(task)),
          )
            .slice(0, 10)
            .map((task) => (
              <article className="overview-task" key={task.id}>
                <h3>
                  <button onClick={() => openTask(task.id)}>
                    {task.title}
                  </button>
                </h3>
                <AgentTree agents={task.agents ?? []} t={t} />
              </article>
            ))}
          {!tasks.some((task) => executing(task) || needsAttention(task)) && (
            <p className="muted">{t('No active tasks')}</p>
          )}
        </section>
      </>
    </PageLayout>
  );
}
