import { Button } from '@miy/ui';
import { ExternalLink, FileCheck2, FileText } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, string, type Detail } from './api';
import type { components } from './api.generated';
import { planNeedsReview, taskStatus } from './agent-state';
import type { Translate } from './i18n';
import { MessageItem } from './views';

type S = components['schemas'];
type AppLink = {
  url: string;
  environment: 'development' | 'production';
  verified: boolean;
};
export function appLink(value?: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) &&
      !url.username &&
      !url.password &&
      !url.hash
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function ResultAppLinks({ task, t }: { task: Detail; t: Translate }) {
  const appId = string(task.context?.app_id);
  const workspaceId = string(task.context?.workspace_id);
  const projectId = string(task.context?.project_id);
  const [snapshot, setSnapshot] = useState<{
    key: string;
    links: AppLink[];
    failed: boolean;
  } | null>(null);
  const [refresh, setRefresh] = useState(0);
  const key = `${task.id}:${appId}:${workspaceId}:${projectId}`;
  const resultId = task.summary?.latest_result?.item_id;
  useEffect(() => {
    if (!appId) return;
    const controller = new AbortController();
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      const links: AppLink[] = [];
      try {
        if (workspaceId) {
          const workspace = await api<S['WorkspaceOut']>(
            `/workbench/workspaces/${encodeURIComponent(workspaceId)}`,
            undefined,
            'GET',
            controller.signal,
          );
          const url = appLink(workspace.preview.portal_url);
          if (
            url &&
            workspace.id === workspaceId &&
            workspace.app_id === appId &&
            (!projectId || workspace.project_id === projectId) &&
            workspace.preview.state === 'ready' &&
            workspace.preview.runtime_revision
          )
            links.push({ url, environment: 'development', verified: true });
        } else {
          const catalog = await api<S['CatalogOut']>(
            '/workbench/catalog',
            undefined,
            'GET',
            controller.signal,
          );
          const app = catalog.items.find((item) => item.app_id === appId);
          const url = appLink(app?.preview_url);
          if (url)
            links.push({ url, environment: 'development', verified: false });
          if (app?.discovery === 'source' || app?.discovery === 'runtime') {
            const installations = await api<S['InstallationsOut']>(
              `/workbench/apps/${encodeURIComponent(appId)}/installations`,
              undefined,
              'GET',
              controller.signal,
            );
            if (!installations.stale && installations.state === 'ready') {
              for (const item of installations.items) {
                const installedUrl = appLink(item.origin);
                if (
                  item.enabled &&
                  installedUrl &&
                  ['development', 'production'].includes(item.environment) &&
                  !links.some((l) => l.url === installedUrl)
                )
                  links.push({
                    url: installedUrl,
                    environment: item.environment as AppLink['environment'],
                    verified: false,
                  });
              }
            }
          }
        }
        if (!controller.signal.aborted)
          setSnapshot({ key, links, failed: false });
      } catch {
        if (!controller.signal.aborted)
          setSnapshot({ key, links: [], failed: true });
      } finally {
        loading = false;
      }
    };
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void load();
    }, 30000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [key, appId, workspaceId, projectId, resultId, refresh]);
  if (!appId) return null;
  const current = snapshot?.key === key ? snapshot : null;
  return (
    <section className="result-links" aria-label={t('App links')}>
      <h3>{t('Check the app')}</h3>
      {!current && <p role="status">{t('Loading app links…')}</p>}
      {current?.failed && (
        <p role="status">
          {t('App links could not be checked.')}{' '}
          <Button variant="ghost" onClick={() => setRefresh((n) => n + 1)}>
            {t('Retry')}
          </Button>
        </p>
      )}
      {current && !current.failed && !current.links.length && (
        <p>{t('An app link will appear when its environment is available.')}</p>
      )}
      <div className="actions">
        {current?.links.map((link) => (
          <a
            className="app-open-link"
            key={link.url}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t(
              link.environment === 'production'
                ? 'Open production app'
                : 'Open development app',
            )}{' '}
            <ExternalLink size={15} aria-hidden="true" />
            <span className="sr-only">{t('Opens in a new tab')}</span>
          </a>
        ))}
      </div>
      <p className="muted">
        {t(
          'Links open a separate app. A completed task does not confirm deployment.',
        )}
      </p>
    </section>
  );
}

export function TaskResults({
  task,
  t,
  openPlan,
  openChanges,
  openChecks,
}: {
  task: Detail;
  t: Translate;
  openPlan: () => void;
  openChanges: () => void;
  openChecks: () => void;
}) {
  const fallback: S['TaskResult'][] = task.items
    .filter(
      (item) => item.type === 'agentMessage' && item.phase === 'final_answer',
    )
    .map((item) => ({
      item_id: string(item.id),
      turn_id: string(item.turn_id),
      text: string(item.text),
      completed_at: null,
      commands: [],
      changed_files: [],
      evidence_truncated: false,
    }))
    .reverse();
  const results = task.results?.length ? task.results : fallback;
  const [selected, setSelected] = useState('latest');
  const current =
    selected === 'latest'
      ? results[0]
      : (results.find((row) => row.item_id === selected) ?? results[0]);
  const commands = current?.commands ?? [];
  const success = commands.filter((row) => row.exitCode === 0).length;
  const failed = commands.filter(
    (row) => typeof row.exitCode === 'number' && row.exitCode !== 0,
  ).length;
  return (
    <div className="result-overview">
      <div className="work-section-heading">
        <h2>{t('Work result')}</h2>
        <span className="work-status">{t(taskStatus(task))}</span>
      </div>
      {planNeedsReview(task) && (
        <section className="result-next-action">
          <h3>{t('Review the plan before implementation')}</h3>
          <p>{t('Check the scope and decide what to build next.')}</p>
          <Button variant="primary" onClick={openPlan}>
            {t('Review plan')}
          </Button>
        </section>
      )}
      <ResultAppLinks task={task} t={t} />
      {!current ? (
        <section className="result-empty">
          <FileText size={28} aria-hidden="true" />
          <h3>{t('Your results will be collected here')}</h3>
          <p>
            {t(
              'Follow the plan, then review the final response, changed files and execution evidence in one place.',
            )}
          </p>
          <Button variant="ghost" onClick={openPlan}>
            {t('Open plan')}
          </Button>
        </section>
      ) : (
        <>
          <div className="result-version">
            <label>
              {t('Result history')}
              <select
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
              >
                <option value="latest">{t('Latest result')}</option>
                {results.slice(1).map((row, index) => (
                  <option key={row.item_id} value={row.item_id}>
                    {t('Previous result')} {index + 1}
                    {row.completed_at
                      ? ` · ${new Date(row.completed_at).toLocaleString(t.locale)}`
                      : ''}
                  </option>
                ))}
              </select>
            </label>
            {current.completed_at && (
              <time dateTime={current.completed_at}>
                {new Date(current.completed_at).toLocaleString(t.locale)}
              </time>
            )}
          </div>
          <section
            className="result-document"
            aria-label={t('Recorded response')}
          >
            <MessageItem
              item={{
                type: 'agentMessage',
                text: current.text,
                phase: 'final_answer',
              }}
              t={t}
              taskId={task.id}
            />
          </section>
          {current.evidence_truncated && (
            <p role="status">
              {t(
                'Some evidence was omitted from this summary. Open execution records for more detail.',
              )}
            </p>
          )}
          <section className="result-evidence">
            <h3>
              <FileCheck2 size={18} aria-hidden="true" />{' '}
              {t('Execution evidence')}
            </h3>
            <p>
              {t('Commands succeeded')}: {success} · {t('Commands failed')}:{' '}
              {failed} · {t('Without an exit code')}:{' '}
              {commands.length - success - failed}
            </p>
            <p className="muted">
              {t(
                'Command success is not proof that every requirement was tested. Check the recorded response for skipped checks.',
              )}
            </p>
            {commands.length > 0 && (
              <details>
                <summary>{t('Commands in this result')}</summary>
                {commands.map((row, i) => (
                  <p key={string(row.id) || i}>
                    <code>{string(row.command)}</code> ·{' '}
                    {row.exitCode == null
                      ? t('Not reported')
                      : `${t('Exit code')} ${row.exitCode}`}
                  </p>
                ))}
              </details>
            )}
            <Button variant="ghost" onClick={openChecks}>
              {t('View task history')}
            </Button>
          </section>
          <section className="result-evidence">
            <h3>{t('Changed files')}</h3>
            {current.changed_files?.length ? (
              <ul>
                {current.changed_files.map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">
                {t('No file changes were reported in this result.')}
              </p>
            )}
            <Button variant="ghost" onClick={openChanges}>
              {t('Review current changes')}
            </Button>
          </section>
        </>
      )}
    </div>
  );
}
