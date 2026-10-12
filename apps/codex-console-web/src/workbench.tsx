import { useEffect, useRef, useState } from 'react';
import { appIconForKey, Button, Dialog, Input } from '@miy/ui';
import {
  ArrowLeft,
  ArrowUpRight,
  Boxes,
  Code2,
  ExternalLink,
  FolderKanban,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { api, record, type Task } from './api';
import type { components } from './api.generated';
import { type Copy, type Translate, errorCopy, korean } from './i18n';
import { ApiError } from './api';
import { PageLayout } from './page-layout';
import { useServices } from './management';
import { SourcePrepare } from './source-prepare';
import { SourceRegistrationExport } from './source-registration-export';
import { SourceRegistrationStatus } from './source-registration-status';
import { ProjectTaskActions } from './project-task-actions';
import { suggestAppId } from './project-defaults';
import {
  currentStep,
  executing,
  needsAttention,
  taskAction,
} from './agent-state';
import {
  StatusPill,
  StudioActivity,
  TaskHistory,
  TaskPreview,
} from './workbench-activity';
import { appLink } from './task-results';
import {
  createWorkspace,
  ProjectWorkspaces,
  workspaceQuery,
} from './workspaces';

type S = components['schemas'];
type App = S['AppDescriptor'];
type Catalog = S['CatalogOut'];
type Maintenance = S['MaintenanceOut'];
type Budget = S['BudgetInput'];
const catalogText = (value: string, t: Translate) =>
  Object.hasOwn(korean, value) ? t(value as Copy) : value;
const appTitle = (app: App, t: Translate) =>
  app.title_translations?.[t.locale ?? 'en-US'] ?? app.title;
const limitationLabels: Record<string, Copy> = {
  source_not_configured: 'Source is not configured.',
  source_missing: 'Configured source paths are missing in this checkout.',
  source_invalid: 'Connected source requires attention.',
  executor_not_configured:
    'Configure an isolated execution environment for this app.',
  preview_not_configured: 'Preview is not configured.',
  release_not_configured: 'Release unit is not configured.',
};
function AppIcon({ app }: { app: App }) {
  const Icon = appIconForKey(app.icon_key ?? 'layout-grid');
  return <Icon size={18} aria-hidden="true" />;
}
export type WorkbenchContext = S['TaskContext'];
export type StartWorkbenchTask = (
  context: WorkbenchContext,
  title: string,
  prompt: string,
) => Promise<void>;

function useResource<T>(path: string, refresh: number) {
  const [poll, setPoll] = useState(0);
  const [result, setResult] = useState<{ path: string; data: T } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') setPoll((value) => value + 1);
    }, 30000);
    const visible = () => {
      if (document.visibilityState !== 'hidden') setPoll((value) => value + 1);
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void api<T>(path, undefined, 'GET', controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setResult({ path, data });
          setError(null);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(reason instanceof ApiError ? reason.code : 'request_failed');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, refresh, poll]);
  return { data: result?.path === path ? result.data : null, error, loading };
}

function ReadError({ code, t }: { code: string; t: Translate }) {
  return (
    <p role="alert" className="danger">
      {t(errorCopy(code))}
    </p>
  );
}
function Revision({ value, t }: { value?: string | null; t: Translate }) {
  return (
    <code title={value ?? undefined}>
      {value ? value.slice(0, 12) : t('Not verified')}
    </code>
  );
}
const stateLabels: Record<string, Copy> = {
  ready: 'Connected',
  unconfigured: 'Connection not configured',
  unavailable: 'Connection unavailable',
  unsupported: 'Integration update required',
  denied: 'Read access denied',
};
function Connection({
  state,
  checkedAt,
  stale,
  t,
}: {
  state: string;
  checkedAt?: string | null;
  stale?: boolean;
  t: Translate;
}) {
  return (
    <p className="muted">
      {t(stateLabels[state] ?? 'Connection unavailable')}
      {checkedAt && (
        <>
          {' '}
          · {t('Last checked')}: {new Date(checkedAt).toLocaleString()}
        </>
      )}
      {stale && <> · {t('Current state not verified')}</>}
    </p>
  );
}

export function WorkbenchApps({
  area,
  t,
  tasks,
  openTask,
  startTask,
  newProjectRequest = 0,
  onNewProjectOpened,
  activityFailed = false,
}: {
  area: 'studio' | 'apps';
  t: Translate;
  tasks: Task[];
  openTask: (id: string) => void;
  startTask: StartWorkbenchTask;
  newTask?: () => void;
  newProjectRequest?: number;
  onNewProjectOpened?: () => void;
  activityFailed?: boolean;
}) {
  const [refresh, setRefresh] = useState(0);
  const { data, error, loading } = useResource<Catalog>(
    '/workbench/catalog',
    refresh,
  );
  const runtime = useResource<S['RuntimeOut']>('/workbench/runtime', refresh);
  const [selected, setSelected] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get('app'),
  );
  const [browser, setBrowser] = useState<'projects' | 'apps'>(() =>
    area === 'apps' || new URLSearchParams(window.location.search).has('app')
      ? 'apps'
      : 'projects',
  );
  const [selectedProject, setSelectedProject] = useState<string | null>(() =>
    area === 'studio'
      ? new URLSearchParams(window.location.search).get('project')
      : null,
  );
  const environmentId = new URLSearchParams(window.location.search).get(
    'environment',
  );
  const [environmentError, setEnvironmentError] = useState<string | null>(null);
  const initializedBrowser = useRef(false);
  useEffect(() => {
    if (area !== 'studio' || selectedProject || !environmentId) return;
    const controller = new AbortController();
    setEnvironmentError(null);
    void api<S['WorkspaceOut']>(
      `/workbench/workspaces/${encodeURIComponent(environmentId)}`,
      undefined,
      'GET',
      controller.signal,
    )
      .then((workspace) => {
        if (controller.signal.aborted) return;
        if (workspace.id !== environmentId || !workspace.project_id)
          throw new ApiError('workspace_changed');
        const params = new URLSearchParams(window.location.search);
        if (
          params.get('environment') !== environmentId ||
          params.has('project')
        )
          return;
        params.set('project', workspace.project_id);
        params.delete('app');
        window.history.replaceState(null, '', `?${params}`);
        initializedBrowser.current = true;
        setBrowser('projects');
        setSelected(null);
        setSelectedProject(workspace.project_id);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setEnvironmentError(
            reason instanceof ApiError ? reason.code : 'request_failed',
          );
      });
    return () => controller.abort();
  }, [area, selectedProject, environmentId]);
  const libraryRef = useRef<HTMLElement>(null);
  const itemElements = useRef(new Map<string, HTMLButtonElement>());
  const lastItem = useRef<string | null>(null);
  const libraryScroll = useRef(0);
  const itemRef = (key: string) => (element: HTMLButtonElement | null) => {
    if (element) itemElements.current.set(key, element);
    else itemElements.current.delete(key);
  };
  const detailPaneRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [appTab, setAppTab] = useState<AppTab>('overview');
  const [newProject, setNewProject] = useState(false);
  const [connectingSource, setConnectingSource] = useState(false);
  const [preparingSource, setPreparingSource] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [projectToDevelop, setProjectToDevelop] = useState<string | null>(null);
  const projectElements = useRef(new Map<string, HTMLDivElement>());
  const managed = record(data).workspaces_available === true;
  const app = data?.items.find((item) => item.app_id === selected);
  const project =
    browser === 'projects'
      ? data?.projects.find((item) => item.id === selectedProject)
      : undefined;
  const projectApp = data?.items.find(
    (item) => item.app_id === project?.app_id,
  );
  const projectExecutorMissing =
    projectApp?.discovery === 'source' &&
    projectApp.source_status === 'ready' &&
    projectApp.execution_status !== 'configured';
  const selectItem = (kind: 'projects' | 'apps', id: string | null) => {
    initializedBrowser.current = true;
    if (id) {
      lastItem.current = `${kind}:${id}`;
      if (libraryRef.current)
        libraryScroll.current =
          libraryRef.current.closest('main')?.scrollTop ?? 0;
    }
    setBrowser(kind);
    setAppTab('overview');
    setSelected(kind === 'apps' ? id : null);
    setSelectedProject(kind === 'projects' ? id : null);
    setNewProject(false);
    setConnectingSource(false);
    const params = new URLSearchParams(window.location.search);
    params.set('view', area);
    params.delete('app');
    params.delete('project');
    params.delete('environment');
    if (id) params.set(kind === 'apps' ? 'app' : 'project', id);
    window.history.replaceState(null, '', `?${params}`);
  };
  useEffect(() => {
    if (!newProjectRequest) return;
    setNewProject(true);
    setConnectingSource(false);
    onNewProjectOpened?.();
  }, [newProjectRequest, onNewProjectOpened]);
  const executorMissing =
    app?.discovery === 'source' &&
    app.source_status === 'ready' &&
    app.execution_status !== 'configured';
  const detailRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!app && !project) return;
    detailRef.current?.focus({ preventScroll: true });
    detailRef.current?.closest('main')?.scrollTo?.({ top: 0 });
  }, [app?.app_id, project?.id]);
  useEffect(() => {
    if (newProject || connectingSource)
      detailPaneRef.current?.focus({ preventScroll: true });
  }, [newProject, connectingSource]);
  useEffect(() => {
    if (!projectToDevelop) return;
    projectElements.current
      .get(projectToDevelop)
      ?.scrollIntoView({ block: 'start' });
  }, [projectToDevelop, data?.projects]);
  const beginManaged = async (project: S['ProjectOut'], prompt: string) => {
    selectItem('projects', project.id);
    setProjectToDevelop(project.id);
    const environments = await api<S['WorkspaceList']>(
      `/workbench/projects/${encodeURIComponent(project.id)}/workspaces`,
    );
    if (!environments.available) throw new ApiError('workspace_unconfigured');
    // Multiple environments require an explicit choice; sessions do not make
    // another environment merely because the user starts a new conversation.
    if (environments.items.length > 1) return;
    let workspace = environments.items[0];
    if (!workspace) {
      try {
        workspace = await createWorkspace(project.id, project.title);
      } finally {
        setRefresh((value) => value + 1);
      }
    }
    if (
      workspace.project_id !== project.id ||
      workspace.app_id !== project.app_id
    )
      throw new ApiError('workspace_changed');
    workspaceQuery(workspace.id);
    if (workspace.state !== 'ready' || !workspace.admission_open) return;
    await startTask(
      {
        area: 'studio',
        purpose: 'development',
        project_id: project.id,
        app_id: project.app_id,
        workspace_id: workspace.id,
      },
      project.title,
      prompt,
    );
  };
  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try {
      await action();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.code : 'request_failed');
    } finally {
      setBusy(false);
    }
  };
  const knownTasks = new Map<string, Task>();
  for (const group of [data?.activity?.projects, data?.activity?.apps])
    for (const activity of Object.values(group ?? {}))
      for (const candidate of [
        activity.latest_task,
        activity.latest_result_task,
      ])
        if (candidate) knownTasks.set(candidate.id, candidate);
  for (const task of tasks) {
    const prior = knownTasks.get(task.id);
    if (!prior || task.updated_at >= prior.updated_at)
      knownTasks.set(task.id, task);
  }
  const allTasks = [...knownTasks.values()].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
  const latestTask = (field: 'project_id' | 'app_id', id: string) =>
    allTasks.find((task) => record(task.context)[field] === id);
  const matchesStatus = (task?: Task, hasResult = false) =>
    statusFilter === 'all' ||
    (statusFilter === 'attention' && !!task && needsAttention(task)) ||
    (statusFilter === 'running' && !!task && executing(task)) ||
    (statusFilter === 'results' &&
      (!!task?.summary?.latest_result || hasResult));
  const filtered = (data?.items ?? [])
    .filter(
      (item) =>
        `${appTitle(item, t)} ${item.title} ${item.app_id} ${item.summary} ${(item.capabilities ?? []).join(' ')}`
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()) &&
        matchesStatus(
          latestTask('app_id', item.app_id),
          !!data?.activity?.apps[item.app_id]?.latest_result_task,
        ),
    )
    .sort((a, b) =>
      (latestTask('app_id', b.app_id)?.updated_at ?? '').localeCompare(
        latestTask('app_id', a.app_id)?.updated_at ?? '',
      ),
    );
  const filteredProjects = (data?.projects ?? [])
    .filter(
      (item) =>
        `${item.title} ${item.summary} ${item.app_id}`
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()) &&
        matchesStatus(
          latestTask('project_id', item.id),
          !!data?.activity?.projects[item.id]?.latest_result_task,
        ),
    )
    .sort((a, b) =>
      (
        latestTask('project_id', b.id)?.updated_at ?? b.created_at
      ).localeCompare(
        latestTask('project_id', a.id)?.updated_at ?? a.created_at,
      ),
    );
  const hasDetail = !!app || !!project || newProject || connectingSource;
  return (
    <PageLayout
      className="wb-browser-view"
      title={area === 'studio' ? 'MIY Studio' : t('App management center')}
      description={t(
        area === 'studio'
          ? 'Develop apps through plans, code changes and verified results.'
          : 'Track app releases, maintenance and development and runtime usage.',
      )}
      actions={
        <>
          <Button
            variant="ghost"
            aria-label={t('Refresh')}
            onClick={() => setRefresh((v) => v + 1)}
          >
            <RefreshCw size={16} />
          </Button>
          <Button
            variant="ghost"
            aria-expanded={connectingSource}
            onClick={() => {
              setConnectingSource((value) => !value);
              setNewProject(false);
            }}
          >
            {t('Connect app source')}
          </Button>
          {area === 'studio' && (
            <>
              <Button
                variant="primary"
                aria-expanded={newProject}
                onClick={() => {
                  setNewProject((value) => !value);
                  setConnectingSource(false);
                }}
              >
                <Plus size={16} />
                {t('Build an app')}
              </Button>
            </>
          )}
        </>
      }
    >
      <div className="wb-status-strip" aria-live="polite">
        {error && <ReadError code={error} t={t} />}
        {environmentError && <ReadError code={environmentError} t={t} />}
        {area === 'apps' && runtime.error && (
          <ReadError code={runtime.error} t={t} />
        )}
        {actionError && <ReadError code={actionError} t={t} />}
        {loading && !data && <p role="status">{t('Loading app catalog')}</p>}
        {data && error && (
          <p className="muted">{t('Showing the last loaded catalog.')}</p>
        )}
        {error && (
          <Button
            variant="ghost"
            onClick={() => setRefresh((value) => value + 1)}
          >
            {t('Retry')}
          </Button>
        )}
      </div>
      <div className={`wb-browser${hasDetail ? ' has-detail' : ''}`}>
        {!hasDetail && (
          <section
            className="wb-library"
            aria-label={t('App and project library')}
            ref={libraryRef}
            tabIndex={-1}
          >
            {area === 'studio' && (
              <StudioActivity
                tasks={allTasks}
                t={t}
                openTask={openTask}
                failed={activityFailed}
              />
            )}
            {area === 'studio' && (
              <h2 className="library-section-title">
                {t('Recent projects and results')}
              </h2>
            )}
            {area === 'studio' ? (
              <div
                className="wb-browser-switch"
                role="group"
                aria-label={t('Browse Studio')}
              >
                <Button
                  variant="ghost"
                  aria-pressed={browser === 'projects'}
                  onClick={() => {
                    selectItem('projects', null);
                    setQuery('');
                  }}
                >
                  <FolderKanban size={15} />
                  {t('App projects')}
                  <span className="wb-count">
                    {data ? data.projects.length : '—'}
                  </span>
                </Button>
                <Button
                  variant="ghost"
                  aria-pressed={browser === 'apps'}
                  onClick={() => {
                    selectItem('apps', null);
                    setQuery('');
                  }}
                >
                  <Boxes size={15} />
                  {t('App catalog')}
                  <span className="wb-count">
                    {data ? data.items.length : '—'}
                  </span>
                </Button>
              </div>
            ) : (
              <div className="wb-library-heading">
                <h2>{t('App catalog')}</h2>
                <span className="wb-count">
                  {data ? data.items.length : '—'}
                </span>
              </div>
            )}
            <div className="wb-library-search">
              <label className="wb-search">
                {t(browser === 'projects' ? 'Find a project' : 'Find an app')}
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t('Search purpose or capability')}
                />
              </label>
              <label className="wb-status-filter">
                {t('Status')}
                <select
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                >
                  <option value="all">{t('All work')}</option>
                  <option value="attention">{t('Needs attention')}</option>
                  <option value="running">{t('Running')}</option>
                  <option value="results">{t('With results')}</option>
                </select>
              </label>
              {area === 'studio' && browser === 'apps' && (
                <Button
                  disabled={busy || !data}
                  onClick={() =>
                    void run(() =>
                      startTask(
                        { area: 'studio', purpose: 'inspection' },
                        t('Review app reuse'),
                        `Review the app catalog and relevant source in this repository for reuse. Requested capability: ${query || 'Ask me which capability I need.'}\nCompare existing apps, explain the source evidence and propose extending an app or creating a new app. This is a read-only planning task.`,
                      ),
                    )
                  }
                >
                  {t('Review app reuse')}
                </Button>
              )}
            </div>
            <div
              className="wb-library-grid"
              role="group"
              aria-label={t(
                browser === 'projects' ? 'Project list' : 'App catalog',
              )}
            >
              {loading && !data && (
                <div className="catalog-placeholder" role="status">
                  {t('Loading app catalog')}
                </div>
              )}
              {browser === 'projects'
                ? filteredProjects.map((item) => {
                    const recent = latestTask('project_id', item.id);
                    const result =
                      data?.activity?.projects[item.id]?.latest_result_task;
                    return (
                      <article key={item.id} className="wb-app wb-project-card">
                        <button
                          className="wb-card-title"
                          ref={itemRef(`projects:${item.id}`)}
                          onClick={() => selectItem('projects', item.id)}
                        >
                          <FolderKanban size={20} aria-hidden="true" />
                          <strong>{item.title}</strong>
                        </button>
                        {recent ? (
                          <StatusPill task={recent} t={t} />
                        ) : (
                          <span className="work-status">
                            {t('Not started')}
                          </span>
                        )}
                        <p className="wb-card-description">
                          {recent && executing(recent) && !recent.pending_count
                            ? currentStep(recent, t)
                            : recent?.summary?.latest_result?.excerpt ||
                              result?.summary?.latest_result?.excerpt ||
                              item.summary}
                        </p>
                        <div className="wb-card-footer">
                          <time
                            dateTime={recent?.updated_at ?? item.created_at}
                          >
                            {new Date(
                              recent?.updated_at ?? item.created_at,
                            ).toLocaleDateString(t.locale)}
                          </time>
                          <Button
                            variant="ghost"
                            onClick={() =>
                              recent
                                ? openTask(recent.id)
                                : selectItem('projects', item.id)
                            }
                          >
                            {t(recent ? taskAction(recent) : 'Open project')}
                            <ArrowUpRight size={15} />
                          </Button>
                        </div>
                      </article>
                    );
                  })
                : filtered.map((item) => {
                    const recent = latestTask('app_id', item.app_id);
                    const installed = runtime.data?.items.find(
                      (row) => row.app_id === item.app_id,
                    );
                    const known =
                      runtime.data?.state === 'ready' &&
                      !runtime.data.stale &&
                      !runtime.error;
                    const url = appLink(item.preview_url);
                    const issues = data?.activity
                      ? (data.activity.apps[item.app_id]?.open_issues ?? 0)
                      : '—';
                    return (
                      <article key={item.app_id} className="wb-app">
                        <button
                          className="wb-card-title"
                          ref={itemRef(`apps:${item.app_id}`)}
                          onClick={() => selectItem('apps', item.app_id)}
                        >
                          <AppIcon app={item} />
                          <strong>{appTitle(item, t)}</strong>
                        </button>
                        <span className="work-status">
                          {t(
                            known && installed
                              ? installed.enabled
                                ? 'Enabled'
                                : 'Disabled'
                              : 'Not verified',
                          )}
                        </span>
                        <p className="wb-card-description">
                          {recent?.summary?.latest_result?.excerpt ||
                            catalogText(item.summary, t)}
                        </p>
                        {area === 'apps' && (
                          <small>
                            {t('Installed revision')}:{' '}
                            {known ? (
                              <Revision
                                value={installed?.installed_revision}
                                t={t}
                              />
                            ) : (
                              t('Not verified')
                            )}{' '}
                            · {t('Open issues')}: {issues}
                          </small>
                        )}
                        <div className="wb-card-footer">
                          {recent ? (
                            <Button
                              variant="ghost"
                              onClick={() => openTask(recent.id)}
                            >
                              {t(taskAction(recent))}
                            </Button>
                          ) : (
                            <span>{t('No related work yet.')}</span>
                          )}
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {t('Open development app')}{' '}
                              <ExternalLink size={14} />
                            </a>
                          ) : (
                            <Button
                              variant="ghost"
                              onClick={() => selectItem('apps', item.app_id)}
                            >
                              {t('Details')}
                            </Button>
                          )}
                        </div>
                      </article>
                    );
                  })}
              {data &&
                !(browser === 'projects' ? filteredProjects : filtered)
                  .length && (
                  <div className="wb-list-empty">
                    <p>
                      {t(
                        browser === 'projects'
                          ? 'No matching projects'
                          : 'No matching apps',
                      )}
                    </p>
                    {query && (
                      <Button variant="ghost" onClick={() => setQuery('')}>
                        {t('Clear search')}
                      </Button>
                    )}
                    {!query &&
                      statusFilter === 'all' &&
                      browser === 'projects' && (
                        <p>
                          {t(
                            'Describe the app you need. Review its plan, follow the work and find the result here.',
                          )}
                        </p>
                      )}
                    {!query &&
                      statusFilter === 'all' &&
                      browser === 'projects' && (
                        <Button
                          variant="primary"
                          onClick={() => setNewProject(true)}
                        >
                          <Plus size={16} />
                          {t('Create a new app')}
                        </Button>
                      )}
                  </div>
                )}
            </div>
          </section>
        )}
        {hasDetail && (
          <div
            className="wb-detail-pane"
            role="region"
            aria-label={t('Details')}
          >
            {hasDetail && (
              <div className="wb-back-toolbar">
                <Button
                  variant="ghost"
                  onClick={() => {
                    selectItem(browser, null);
                    requestAnimationFrame(() => {
                      const element =
                        itemElements.current.get(lastItem.current ?? '') ??
                        libraryRef.current;
                      element?.focus({ preventScroll: true });
                      libraryRef.current
                        ?.closest('main')
                        ?.scrollTo?.({ top: libraryScroll.current });
                    });
                  }}
                >
                  <ArrowLeft size={16} />
                  {t('Back to list')}
                </Button>
              </div>
            )}
            <div className="wb-detail-body" ref={detailPaneRef} tabIndex={-1}>
              {data && (
                <>
                  {connectingSource && (
                    <SourceBindingForm
                      t={t}
                      onSaved={(appId) => {
                        selectItem('apps', appId);
                        setConnectingSource(false);
                        setRefresh((value) => value + 1);
                      }}
                    />
                  )}
                  {newProject && (
                    <ProjectForm
                      t={t}
                      catalog={data}
                      busy={busy}
                      onCreate={(body) =>
                        void run(async () => {
                          const project = await api<S['ProjectOut']>(
                            '/workbench/projects',
                            body,
                          );
                          setNewProject(false);
                          selectItem('projects', project.id);
                          setRefresh((v) => v + 1);
                          if (managed) {
                            await beginManaged(
                              project,
                              `${project.summary}\nCompare existing app capabilities for reuse, then inspect this managed app source and its public platform contracts and prepare a plan. Keep implementation within this app's approved source. The server owns local checkpoints and runtime refresh.`,
                            );
                            return;
                          }
                          await startTask(
                            {
                              area: 'studio',
                              purpose: 'development',
                              project_id: project.id,
                              app_id: project.app_id,
                            },
                            project.title,
                            `${project.summary}\n\nReuse decision: ${project.reuse_decision}\n${project.reuse_notes}\n\nPlan this app using the versioned independent app manifest and supported runtime profiles. Identify an isolated app source and execution environment before implementation. An unconnected project is planning only; do not implement its business code in the platform checkout.`,
                          );
                        })
                      }
                    />
                  )}
                  {app &&
                    browser === 'apps' &&
                    !newProject &&
                    !connectingSource && (
                      <section
                        className="wb-app-detail"
                        ref={detailRef}
                        tabIndex={-1}
                        aria-label={t('Selected app')}
                      >
                        <div className="wb-heading">
                          <div>
                            <span className="wb-eyebrow">
                              {t('App catalog')}
                            </span>
                            <h2>{appTitle(app, t)}</h2>
                            <p>{catalogText(app.summary, t)}</p>
                          </div>
                          <div className="actions">
                            <Button
                              variant="primary"
                              disabled={busy || (!managed && executorMissing)}
                              onClick={() =>
                                void run(() =>
                                  managed && area === 'studio'
                                    ? (async () => {
                                        const project =
                                          data.projects.find(
                                            (item) =>
                                              item.app_id === app.app_id,
                                          ) ??
                                          (await api<S['ProjectOut']>(
                                            '/workbench/projects',
                                            {
                                              app_id: app.app_id,
                                              title: appTitle(app, t),
                                              summary: t(
                                                'Existing app selected. Review its source before extending it.',
                                              ),
                                              reuse_decision: 'extend',
                                              reuse_notes: t(
                                                'Existing app selected. Review its source before extending it.',
                                              ),
                                            },
                                          ));
                                        setRefresh((value) => value + 1);
                                        await beginManaged(
                                          project,
                                          `Inspect the ${app.app_id} app in this managed development environment. Ask for the requested change and acceptance criteria, then prepare a plan. Use the current source and public platform contracts.`,
                                        );
                                      })()
                                    : startTask(
                                        {
                                          area,
                                          purpose:
                                            app.source_status === 'ready'
                                              ? 'development'
                                              : 'inspection',
                                          app_id: app.app_id,
                                        },
                                        `${appTitle(app, t)}: ${t(app.source_status === 'ready' ? 'Develop app' : 'Inspect app registration')}`,
                                        app.source_status === 'ready'
                                          ? `Inspect the ${app.app_id} app and its repository instructions. Ask for the requested change and acceptance criteria, then prepare a plan.`
                                          : `Inspect registration of ${app.app_id}. Its development source is unavailable. Find authoritative source and release configuration; do not guess paths or deployment targets. Report the evidence and propose the missing configuration. This is a read-only planning task.`,
                                      ),
                                )
                              }
                            >
                              <Code2 size={16} />
                              {t(
                                app.source_status === 'ready'
                                  ? 'Develop app'
                                  : 'Inspect app registration',
                              )}
                            </Button>
                            {app.preview_url && (
                              <a
                                href={app.preview_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {t('Open development app')}{' '}
                                <ExternalLink size={13} />
                              </a>
                            )}
                          </div>
                        </div>
                        <nav
                          className="app-detail-tabs"
                          aria-label={t('App management sections')}
                        >
                          {appTabs.map(([id, label]) => (
                            <button
                              key={id}
                              aria-pressed={appTab === id}
                              onClick={() => setAppTab(id)}
                            >
                              {t(label)}
                            </button>
                          ))}
                        </nav>
                        <section
                          hidden={appTab !== 'connections'}
                          className="wb-detail-section"
                          aria-label={t('Source and connections')}
                        >
                          <h3>{t('Source and connections')}</h3>
                          {(app.limitations ?? []).map((reason) => (
                            <p key={reason} className="muted">
                              {t(limitationLabels[reason])}
                            </p>
                          ))}
                          {app.execution_status === 'configured' && (
                            <p className="muted">
                              {t(
                                'Execution environment configured; availability checked when starting work.',
                              )}
                            </p>
                          )}
                          {app.preview_status === 'configured' && (
                            <p className="muted">
                              {t(
                                'Preview configured; availability not verified',
                              )}
                            </p>
                          )}
                          {app.deployment_status === 'configured' && (
                            <p className="muted">
                              {t('Release configured; deployment not verified')}
                            </p>
                          )}
                          <dl className="wb-facts">
                            <div>
                              <dt>{t('Release unit')}</dt>
                              <dd>{app.release_unit ?? t('Not configured')}</dd>
                            </div>
                            <div>
                              <dt>{t('Source paths')}</dt>
                              <dd>
                                {(app.source_paths ?? []).map((path) => (
                                  <code key={path}>
                                    {path}
                                    <br />
                                  </code>
                                ))}
                              </dd>
                            </div>
                          </dl>
                          {app.discovery !== 'checkout' && app.discovery && (
                            <SourceBindingForm
                              key={`source-binding:${app.app_id}`}
                              app={app}
                              t={t}
                              onSaved={() => setRefresh((value) => value + 1)}
                            />
                          )}
                          {app.release_unit === 'miy-app' && (
                            <p className="muted">
                              {t(
                                'This app ships with the MIY release. Deployment and rollback apply to that release.',
                              )}
                            </p>
                          )}
                        </section>
                        {
                          <AppManagement
                            key={`app-management:${app.app_id}`}
                            app={app}
                            tab={appTab}
                            onTab={setAppTab}
                            runtime={
                              runtime.data && runtime.error
                                ? {
                                    ...runtime.data,
                                    state: 'unavailable',
                                    stale: true,
                                  }
                                : runtime.data
                            }
                            t={t}
                            refresh={refresh}
                            startTask={startTask}
                            openTask={openTask}
                            tasks={tasks}
                          />
                        }
                        {appTab === 'overview' &&
                          app.discovery &&
                          app.discovery !== 'checkout' && (
                            <AppInstallations
                              key={`app-installations:${app.app_id}`}
                              appId={app.app_id}
                              refresh={refresh}
                              t={t}
                              startTask={
                                app.source_status === 'ready' &&
                                !executorMissing
                                  ? startTask
                                  : undefined
                              }
                            />
                          )}
                        {appTab === 'overview' &&
                          data.activity?.apps[app.app_id]?.latest_result_task &&
                          data.activity.apps[app.app_id].latest_result_task!
                            .id !== latestTask('app_id', app.app_id)?.id && (
                            <section className="wb-detail-section">
                              <h3>{t('Latest result')}</h3>
                              <TaskPreview
                                task={
                                  data.activity.apps[app.app_id]
                                    .latest_result_task!
                                }
                                t={t}
                                openTask={openTask}
                              />
                            </section>
                          )}
                        {appTab === 'history' && (
                          <TaskHistory
                            tasks={tasks}
                            appId={app.app_id}
                            t={t}
                            openTask={openTask}
                          />
                        )}
                        {appTab === 'overview' &&
                          latestTask('app_id', app.app_id) && (
                            <section className="wb-detail-section">
                              <h3>{t('Latest work')}</h3>
                              <TaskPreview
                                task={latestTask('app_id', app.app_id)!}
                                t={t}
                                openTask={openTask}
                              />
                            </section>
                          )}
                      </section>
                    )}
                  {project && !newProject && !connectingSource && (
                    <section
                      className="wb-project-detail"
                      aria-label={t('Selected project')}
                      ref={detailRef}
                      tabIndex={-1}
                    >
                      <div
                        className="stack wb-project-content"
                        key={project.id}
                        ref={(element) => {
                          if (element)
                            projectElements.current.set(project.id, element);
                          else projectElements.current.delete(project.id);
                        }}
                      >
                        <div className="wb-heading">
                          <div>
                            <span className="wb-eyebrow">
                              {t('App projects')}
                            </span>
                            <h2>{project.title}</h2>
                            <p className="muted">{project.summary}</p>
                          </div>
                          <div className="actions">
                            {projectApp?.preview_url && (
                              <a
                                href={projectApp.preview_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {t('Open development app')}{' '}
                                <ExternalLink size={13} />
                              </a>
                            )}
                            {!managed && project.reuse_decision === 'new' && (
                              <Button
                                aria-expanded={preparingSource === project.id}
                                onClick={() =>
                                  setPreparingSource((current) =>
                                    current === project.id ? null : project.id,
                                  )
                                }
                              >
                                {t('Prepare app source')}
                              </Button>
                            )}
                            {!managed && (
                              <ProjectTaskActions
                                project={project}
                                source={projectApp}
                                busy={busy}
                                scope={selected ?? ''}
                                registrationAvailable={
                                  data.registration_authorization_available
                                }
                                t={t}
                                onStart={(purpose) =>
                                  run(() =>
                                    startTask(
                                      {
                                        area: 'studio',
                                        purpose,
                                        project_id: project.id,
                                        app_id: project.app_id,
                                      },
                                      project.title,
                                      purpose === 'registration'
                                        ? "Inspect this registration Task's committed app source. Explain the personal, inactive development registration and plan the next step. Use miy_app_registration context; registration requires the owner's MIY authorization and explicit implementation approval. Never treat a receipt as execution readiness or deployment."
                                        : `${project.summary}\nReview existing work and propose the next development step using this task's source binding. If no isolated app source is connected, plan the setup before implementation.`,
                                    ),
                                  )
                                }
                              />
                            )}
                          </div>
                        </div>
                        {latestTask('project_id', project.id) && (
                          <section className="project-next-work">
                            <h3>{t('Continue your work')}</h3>
                            <TaskPreview
                              task={latestTask('project_id', project.id)!}
                              t={t}
                              openTask={openTask}
                            />
                          </section>
                        )}
                        {data.activity?.projects[project.id]
                          ?.latest_result_task &&
                          data.activity.projects[project.id].latest_result_task!
                            .id !==
                            latestTask('project_id', project.id)?.id && (
                            <section className="project-next-work">
                              <h3>{t('Latest result')}</h3>
                              <TaskPreview
                                task={
                                  data.activity.projects[project.id]
                                    .latest_result_task!
                                }
                                t={t}
                                openTask={openTask}
                              />
                            </section>
                          )}
                        <TaskHistory
                          tasks={tasks}
                          projectId={project.id}
                          t={t}
                          openTask={openTask}
                        />
                        {managed && (
                          <ProjectWorkspaces
                            project={project}
                            t={t}
                            tasks={tasks}
                            openTask={openTask}
                            startTask={startTask}
                          />
                        )}
                        {!managed && projectExecutorMissing && (
                          <p className="muted">
                            {t(
                              'Configure an isolated execution environment for this app.',
                            )}
                          </p>
                        )}
                        {!managed && preparingSource === project.id && (
                          <SourcePrepare
                            key={`source-prepare:${project.id}`}
                            projectId={project.id}
                            appId={project.app_id}
                            t={t}
                            onPrepared={() => setRefresh((value) => value + 1)}
                          />
                        )}
                        {!managed &&
                          projectApp?.discovery === 'source' &&
                          projectApp.source_status === 'ready' && (
                            <SourceRegistrationExport
                              key={`source-registration-export:${project.id}`}
                              projectId={project.id}
                              t={t}
                            />
                          )}
                        {!managed &&
                          projectApp?.discovery === 'source' &&
                          projectApp.source_version > 0 && (
                            <SourceRegistrationStatus
                              projectId={project.id}
                              appId={project.app_id}
                              bindingVersion={projectApp.source_version}
                              t={t}
                            />
                          )}
                      </div>
                    </section>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </PageLayout>
  );
}

export function AppInstallations({
  appId,
  refresh,
  t,
  startTask,
}: {
  appId: string;
  refresh: number;
  t: Translate;
  startTask?: StartWorkbenchTask;
}) {
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const inspect = async (
    item: S['InstallationObservation'],
    purpose: 'inspection' | 'deployment' | 'recovery',
  ) => {
    if (!startTask || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const request =
        purpose === 'inspection'
          ? 'Inspect the selected development app installation and existing delivery requests with miy_app_delivery. Report verified records and unresolved state. Do not mutate source, registrations or deployments.'
          : purpose === 'deployment'
            ? 'Plan a development preview deployment for this selected app installation. Use miy_app_delivery context and existing request status. Identify source changes, the exact verified release, permissions and required checks. The implementation may create a local checkpoint in this app checkout, sync its definition, request a core build and deploy the verified release. Publication and production are outside this request. Never rerun an uncertain request as a new operation.'
            : 'Plan recovery of this selected development app installation. Inspect its current release and existing requests with miy_app_delivery first. Identify a compatible verified previous release and distinguish image rollback from database recovery. Ask for the target only if ambiguous. Never replay unknown work or perform database downgrade.';
      await startTask(
        { app_id: appId, installation_id: item.id, purpose, area: 'apps' },
        `${appId} · ${t(purpose === 'inspection' ? 'Inspect installation' : purpose === 'deployment' ? 'Plan preview deployment' : 'Plan app recovery')}`,
        request,
      );
    } catch (reason) {
      setActionError(
        reason instanceof ApiError ? reason.code : 'request_failed',
      );
    } finally {
      setBusy(false);
    }
  };
  const { data, error, loading } = useResource<S['InstallationsOut']>(
    `/workbench/apps/${encodeURIComponent(appId)}/installations`,
    refresh,
  );
  const labels: Record<string, Copy> = {
    configured: 'Configured',
    ready: 'Ready',
    queued: 'Queued',
    running: 'Running',
    cleanup: 'Cleanup required',
    succeeded: 'Succeeded',
    failed: 'Failed',
    unknown: 'Unknown',
  };
  return (
    <section className="stack" aria-label={t('App installations')}>
      <h3>{t('App installations')}</h3>
      <p className="muted">
        {t('Deployment records are not live health checks.')}
      </p>
      {error && <ReadError code={error} t={t} />}
      {actionError && <ReadError code={actionError} t={t} />}
      {loading && !data && (
        <p className="muted">{t('Loading app installations')}</p>
      )}
      {data && (
        <Connection
          state={error ? 'unavailable' : data.state}
          stale={!!error || data.stale}
          checkedAt={data.checked_at}
          t={t}
        />
      )}
      {data?.state === 'ready' && !data.items.length && (
        <p>{t('No app installations')}</p>
      )}
      {data?.items.map((item) => (
        <article className="wb-panel stack" key={item.id}>
          <strong>
            {t(
              item.environment === 'development' ? 'Development' : 'Production',
            )}{' '}
            · {t(item.enabled ? 'Enabled' : 'Disabled')}
          </strong>
          <span>{t(labels[item.state] ?? 'Unknown')}</span>
          <a href={item.origin} target="_blank" rel="noopener noreferrer">
            {item.origin} <ExternalLink size={13} />
          </a>
          <small>
            {t('Installation ID')}: <code>{item.id}</code>
          </small>
          {startTask &&
            item.environment === 'development' &&
            item.delivery_configured === false && (
              <div className="stack">
                {!error && data.state === 'ready' && !data.stale && (
                  <p className="muted">
                    {t(
                      "Deployment connection is pending. Enable use in the registration task's My development preview settings, then ask the Workbench administrator to connect delivery.",
                    )}
                  </p>
                )}
                <div className="wb-actions">
                  <Button disabled>{t('Plan preview deployment')}</Button>
                </div>
              </div>
            )}
          {startTask &&
            item.environment === 'development' &&
            item.delivery_configured && (
              <div className="wb-actions">
                <Button
                  disabled={busy}
                  onClick={() => void inspect(item, 'inspection')}
                >
                  {t('Inspect installation')}
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => void inspect(item, 'deployment')}
                >
                  {t('Plan preview deployment')}
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => void inspect(item, 'recovery')}
                >
                  {t('Plan app recovery')}
                </Button>
              </div>
            )}
          <span>
            {t('Installed revision')}:{' '}
            <Revision value={item.source_revision} t={t} />
          </span>
          {item.artifact_digest && (
            <code style={{ overflowWrap: 'anywhere' }}>
              {item.artifact_digest}
            </code>
          )}
          {item.deployment ? (
            <>
              <span>
                {t(
                  item.deployment.action === 'rollback'
                    ? 'Rollback'
                    : 'Deployment',
                )}
                : {t(labels[item.deployment.state] ?? 'Unknown')}
              </span>
              <small>
                {t('Deployment request')}:{' '}
                <code>{item.deployment.request_id}</code>
              </small>
              <small>
                {t('Deployment record updated')}:{' '}
                {new Date(item.deployment.updated_at).toLocaleString()}
              </small>
              {item.deployment.failure_code && (
                <code>{item.deployment.failure_code}</code>
              )}
              {['unknown', 'running', 'cleanup'].includes(
                item.deployment.state,
              ) && (
                <p className="muted">
                  {t('Check the existing request before retrying.')}
                </p>
              )}
            </>
          ) : (
            <span className="muted">{t('No deployment evidence')}</span>
          )}
        </article>
      ))}
    </section>
  );
}

function ProjectForm({
  t,
  catalog,
  busy,
  onCreate,
}: {
  t: Translate;
  catalog: Catalog;
  busy: boolean;
  onCreate: (body: S['ProjectInput']) => void;
}) {
  const [title, setTitle] = useState('');
  const [appId, setAppId] = useState('');
  const [summary, setSummary] = useState('');
  const [notes, setNotes] = useState('');
  const [decision, setDecision] = useState<'new' | 'extend'>('new');
  const suggested = suggestAppId(title, [
    ...catalog.items.map((item) => item.app_id),
    ...catalog.projects.map((project) => project.app_id),
  ]);
  const chosenAppId = decision === 'new' ? appId || suggested : appId;
  const reuseNotes =
    notes ||
    t(
      decision === 'new'
        ? 'New app requested. Compare existing apps before implementation.'
        : 'Existing app selected. Review its source before extending it.',
    );
  return (
    <form
      className="wb-panel stack"
      onSubmit={(e) => {
        e.preventDefault();
        onCreate({
          title,
          app_id: chosenAppId,
          summary,
          reuse_decision: decision,
          reuse_notes: reuseNotes,
        });
      }}
    >
      <h2>{t('New app project')}</h2>
      <p className="muted">
        {t(
          'Name the app and describe the work you want it to help with. Other project settings are suggested automatically.',
        )}
      </p>
      <label>
        {t('Project title')}
        <Input
          value={title}
          maxLength={200}
          required
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <label>
        {t('Requirements and acceptance criteria')}
        <textarea
          value={summary}
          maxLength={4000}
          required
          onChange={(e) => setSummary(e.target.value)}
        />
      </label>
      <details>
        <summary>{t('Advanced project settings')}</summary>
        <label>
          {t('Reuse decision')}
          <select
            value={decision}
            onChange={(e) => {
              setDecision(e.target.value as 'new' | 'extend');
              setAppId('');
            }}
          >
            <option value="new">{t('Create a new app')}</option>
            <option value="extend">{t('Extend an existing app')}</option>
          </select>
        </label>
        <label>
          {t('App identifier')}
          {decision === 'extend' ? (
            <select
              required
              value={chosenAppId}
              onChange={(e) => setAppId(e.target.value)}
            >
              <option value="">{t('Choose an app')}</option>
              {catalog.items.map((app) => (
                <option key={app.app_id} value={app.app_id}>
                  {appTitle(app, t)}
                </option>
              ))}
            </select>
          ) : (
            <Input
              value={chosenAppId}
              maxLength={64}
              minLength={2}
              pattern="[a-z](?:[a-z0-9]|-){1,63}"
              required
              onChange={(e) => setAppId(e.target.value)}
            />
          )}
        </label>
        <label>
          {t('Existing apps reviewed and decision rationale')}
          <textarea
            value={reuseNotes}
            maxLength={4000}
            required
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        <p className="muted">
          {t(
            'You can change the suggested app identifier and reuse notes. Registration and development permissions are checked separately.',
          )}
        </p>
      </details>
      <Button variant="primary" disabled={busy} type="submit">
        {t('Create project and plan')}
      </Button>
    </form>
  );
}

function SourceBindingForm({
  app,
  t,
  onSaved,
}: {
  app?: App;
  t: Translate;
  onSaved: (appId: string) => void;
}) {
  const [appId, setAppId] = useState(app?.app_id ?? '');
  const [root, setRoot] = useState(app?.source_root ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="wb-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        setBusy(true);
        setError(null);
        void api(
          `/workbench/apps/${encodeURIComponent(appId)}/source`,
          { repository_root: root, version: app?.source_version ?? 0 },
          'PUT',
        )
          .then(() => onSaved(appId))
          .catch((reason) =>
            setError(
              reason instanceof ApiError ? reason.code : 'request_failed',
            ),
          )
          .finally(() => setBusy(false));
      }}
    >
      <h3>{t('Application source')}</h3>
      <p className="muted">
        {t(
          'Use an owner-approved checkout containing the matching app.manifest.json.',
        )}
      </p>
      {!app && (
        <label>
          {t('App identifier')}
          <Input
            required
            value={appId}
            onChange={(event) => setAppId(event.target.value)}
          />
        </label>
      )}
      <label>
        {t('Repository checkout path')}
        <Input
          required
          value={root}
          onChange={(event) => setRoot(event.target.value)}
        />
      </label>
      {error && <ReadError code={error} t={t} />}
      <Button type="submit" disabled={busy || !appId || !root}>
        {t('Connect app source')}
      </Button>
    </form>
  );
}

type AppTab = 'overview' | 'history' | 'issues' | 'usage' | 'connections';
const appTabs: [AppTab, Copy][] = [
  ['overview', 'Overview'],
  ['history', 'Work results'],
  ['issues', 'Issue management'],
  ['usage', 'Usage and budget'],
  ['connections', 'Connection settings'],
];

function AppManagement({
  tab,
  onTab,
  app,
  runtime,
  t,
  refresh,
  startTask,
  openTask,
  tasks,
}: {
  tab: AppTab;
  onTab: (value: AppTab) => void;
  app: App;
  runtime: S['RuntimeOut'] | null;
  t: Translate;
  refresh: number;
  startTask: StartWorkbenchTask;
  openTask: (id: string) => void;
  tasks: Task[];
}) {
  const [revision, setRevision] = useState(0);
  const usage = useResource<S['UsageOut']>(
    `/workbench/apps/${app.app_id}/usage`,
    refresh + revision,
  );
  const patches = useResource<Maintenance[]>(
    `/workbench/apps/${app.app_id}/maintenance`,
    refresh + revision,
  );
  const evidence = useResource<S['PlatformOut']>(
    '/workbench/platform',
    refresh + revision,
  );
  const installed = runtime?.items.find((row) => row.app_id === app.app_id);
  const installedRevision =
    app.release_unit === 'miy-workbench'
      ? evidence.data?.workbench_release?.source_dirty
        ? null
        : evidence.data?.workbench_release?.source_revision
      : installed?.installed_revision;
  const installationStale =
    app.release_unit === 'miy-workbench'
      ? !!evidence.error || !evidence.data?.workbench_release
      : runtime?.stale !== false;
  const [edit, setEdit] = useState<Maintenance | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<void>) => {
    if (busy) return false;
    setBusy(true);
    setError(null);
    try {
      await action();
      setRevision((v) => v + 1);
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.code : 'request_failed');
      return false;
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {error && edit === undefined && <ReadError code={error} t={t} />}
      <section
        hidden={tab !== 'overview'}
        className="wb-detail-section"
        aria-label={t('Installation and release')}
      >
        <h3>{t('Installation and release')}</h3>
        {runtime && (
          <Connection
            state={runtime.state}
            stale={runtime.stale}
            checkedAt={runtime.checked_at}
            t={t}
          />
        )}
        <dl className="wb-facts">
          <div>
            <dt>{t('Installed revision')}</dt>
            <dd>
              <Revision value={installedRevision} t={t} />
            </dd>
          </div>
          <div>
            <dt>{t('App availability')}</dt>
            <dd>
              {installed && !runtime?.stale
                ? t(installed.enabled ? 'Enabled' : 'Disabled')
                : t('Not verified')}
            </dd>
          </div>
          <div>
            <dt>{t('Runtime AI')}</dt>
            <dd>
              {installed && !runtime?.stale
                ? t(installed.runtime_ai ? 'Registered' : 'Not registered')
                : t('Not verified')}
            </dd>
          </div>
        </dl>
        {evidence.error && (
          <>
            <ReadError code={evidence.error} t={t} />
            <p className="muted">{t('Current state not verified')}</p>
          </>
        )}
        {evidence.data &&
          ['miy-app', 'miy-workbench'].includes(app.release_unit ?? '') && (
            <p className="muted">
              {t('Development revision CI')}:{' '}
              {evidence.error || evidence.data.gitlab.stale
                ? t('Not verified')
                : (evidence.data.gitlab.pipelines?.find(
                    (p) => p.revision === evidence.data?.git?.head,
                  )?.status ?? t('Not verified'))}{' '}
              · {t('Development revision')}:{' '}
              <Revision value={evidence.data.git?.head} t={t} />
            </p>
          )}
      </section>
      {tab === 'overview' && (
        <div className="app-overview-actions">
          <Button onClick={() => onTab('issues')}>
            {t('Open issues')}:{' '}
            {patches.data?.filter((row) =>
              ['open', 'planned'].includes(row.state),
            ).length ?? '—'}
          </Button>
        </div>
      )}
      <section
        className="wb-detail-section"
        hidden={tab !== 'usage'}
        aria-label={t('Monthly usage and budget')}
      >
        {usage.error && <ReadError code={usage.error} t={t} />}
        {usage.loading && <p role="status">{t('Loading usage')}</p>}
        {usage.data && (
          <UsagePanel
            t={t}
            data={
              usage.error
                ? { ...usage.data, runtime_state: 'unavailable', stale: true }
                : usage.data
            }
            busy={busy}
            error={error}
            onBudget={(body) =>
              run(async () => {
                await api(`/workbench/apps/${app.app_id}/budget`, body, 'PUT');
              })
            }
          />
        )}
      </section>
      <section
        className="wb-detail-section"
        hidden={tab !== 'issues'}
        aria-label={t('Maintenance and patches')}
      >
        <div className="wb-heading">
          <h3>{t('Maintenance and patches')}</h3>
          <Button onClick={() => setEdit(null)}>
            <Plus size={14} />
            {t('Register a problem')}
          </Button>
        </div>
        {patches.error && <ReadError code={patches.error} t={t} />}
        <Dialog
          open={edit !== undefined}
          onOpenChange={(open) => {
            if (!open) setEdit(undefined);
          }}
          title={t(edit ? 'Edit problem' : 'Register a problem')}
          closeLabel={t('Close')}
        >
          {error && <ReadError code={error} t={t} />}
          {edit !== undefined && (
            <MaintenanceForm
              key={edit?.id ?? 'new'}
              t={t}
              item={edit}
              busy={busy}
              onCancel={() => setEdit(undefined)}
              onSave={(body) =>
                void run(async () => {
                  await api(
                    `/workbench/apps/${app.app_id}/maintenance${edit ? `/${edit.id}` : ''}`,
                    body,
                    edit ? 'PUT' : 'POST',
                  );
                  setEdit(undefined);
                })
              }
            />
          )}
        </Dialog>
        {patches.data?.length === 0 && (
          <p className="muted">{t('No maintenance items')}</p>
        )}
        {patches.data?.map((patch) => (
          <article className="wb-patch" key={patch.id}>
            <div>
              <strong>{patch.title}</strong>
              <p>{patch.notes}</p>
              <small>
                {patch.owner} {patch.due_on} ·{' '}
                {t(
                  patch.state === 'cancelled'
                    ? 'Cancelled'
                    : patch.state === 'verified'
                      ? 'Verification completed'
                      : patch.state === 'planned'
                        ? 'Planned'
                        : 'Open',
                )}
              </small>
              {patch.target_revision && (
                <p className="muted">
                  {t('Target revision')}:{' '}
                  <Revision value={patch.target_revision} t={t} /> ·{' '}
                  {t(
                    installedRevision === patch.target_revision &&
                      !installationStale
                      ? 'Installation observed'
                      : 'Installation not verified',
                  )}
                </p>
              )}
              {patch.task_id && (
                <Button
                  variant="ghost"
                  onClick={() => openTask(patch.task_id!)}
                >
                  {t('Open linked work')}
                </Button>
              )}
            </div>
            <div className="actions">
              {['miy-app', 'miy-workbench'].includes(app.release_unit ?? '') &&
                patch.target_revision &&
                patch.state !== 'verified' &&
                patch.state !== 'cancelled' && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await api(
                          `/workbench/apps/${app.app_id}/maintenance/${patch.id}/verify`,
                          { version: patch.version },
                        );
                      })
                    }
                  >
                    {t('Verify patch installation')}
                  </Button>
                )}
              <Button onClick={() => setEdit(patch)}>{t('Edit')}</Button>
              <Button
                disabled={
                  busy ||
                  app.source_status !== 'ready' ||
                  (app.discovery === 'source' &&
                    app.execution_status !== 'configured') ||
                  patch.state === 'cancelled' ||
                  patch.state === 'verified'
                }
                onClick={() =>
                  void run(() =>
                    startTask(
                      {
                        area: 'apps',
                        purpose: 'development',
                        app_id: app.app_id,
                        maintenance_id: patch.id,
                      },
                      patch.title,
                      `Investigate this maintenance item for ${app.app_id}:\n${patch.title}\n${patch.notes}\nRead the repository instructions. Plan a fix, focused checks and release impact. Publishing and deployment require explicit authorization.`,
                    ),
                  )
                }
              >
                {t('Prepare a patch')}
              </Button>
            </div>
          </article>
        ))}
        {tasks.some(
          (task) =>
            record(task.context).app_id === app.app_id &&
            task.status === 'failed',
        ) && (
          <p role="status" className="danger">
            {t('A related task needs attention.')}
          </p>
        )}
      </section>
    </>
  );
}

const alerts: Record<string, Copy> = {
  task_failed: 'A related task needs attention.',
  patch_overdue: 'A maintenance target date has passed.',
  development_budget_exceeded: 'Development token budget exceeded.',
  runtime_budget_exceeded: 'Runtime token budget exceeded.',
  runtime_errors: 'Runtime AI errors were reported.',
  cost_budget_exceeded: 'Reported cost exceeds the budget.',
};
function UsagePanel({
  error,
  t,
  data,
  busy,
  onBudget,
}: {
  t: Translate;
  error?: string | null;
  data: S['UsageOut'];
  busy: boolean;
  onBudget: (value: Budget) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState<Budget | null>(null);
  const format = (value?: number | null) =>
    value == null ? t('Not reported') : value.toLocaleString();
  return (
    <section className="wb-usage">
      <div className="wb-heading">
        <h3>
          {t('Monthly usage and budget')} · {data.month} UTC
        </h3>
        <Button onClick={() => setEditing(editing ? null : data.budget)}>
          {t('Edit budget')}
        </Button>
      </div>
      <Connection
        state={data.runtime_state}
        checkedAt={data.runtime_checked_at}
        stale={data.stale}
        t={t}
      />
      <dl className="wb-facts">
        <div>
          <dt>{t('Observed development tokens')}</dt>
          <dd>
            {format(data.development_tokens)}
            <br />
            <small>
              {t('Token budget')}: {format(data.budget.development_tokens)}
            </small>
          </dd>
        </div>
        <div>
          <dt>{t('Runtime tokens')}</dt>
          <dd>
            {format(data.runtime?.total_tokens)}
            <br />
            <small>
              {t('Token budget')}: {format(data.budget.runtime_tokens)}
            </small>
          </dd>
        </div>
        <div>
          <dt>{t('App opens')}</dt>
          <dd>{format(data.runtime?.app_opens)}</dd>
        </div>
        <div>
          <dt>{t('Reported cost')}</dt>
          <dd>
            {data.runtime?.amount_minor != null && data.runtime.currency
              ? new Intl.NumberFormat(undefined, {
                  style: 'currency',
                  currency: data.runtime.currency,
                }).format(
                  data.runtime.amount_minor /
                    (data.runtime.currency === 'KRW' ? 1 : 100),
                )
              : t('Amount not provided')}
          </dd>
        </div>
      </dl>
      <p className="muted">
        {t(
          'Development usage includes observed events only. Unreported subscription charges are not zero.',
        )}
      </p>
      {(data.unreported_tasks > 0 ||
        (data.runtime?.unreported_calls ?? 0) > 0 ||
        data.runtime?.complete === false) && (
        <p className="muted">
          {t('Some usage is unreported; totals are incomplete.')}
        </p>
      )}
      {data.budget.amount_minor != null && (
        <p>
          {t('Monthly cost budget')}:{' '}
          {data.budget.amount_minor /
            (data.budget.currency === 'KRW' ? 1 : 100)}{' '}
          {data.budget.currency} ·{' '}
          {t('Cost comparison requires reported charges.')}
        </p>
      )}
      {data.alerts.length > 0 && (
        <ul className="wb-alerts" aria-label={t('Management alerts')}>
          {data.alerts.map((key) => (
            <li key={key}>
              {t(alerts[key] ?? 'A related task needs attention.')}
            </li>
          ))}
        </ul>
      )}
      <Dialog
        open={!!editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        title={t('Edit budget')}
        closeLabel={t('Close')}
      >
        <p className="muted">
          {t(
            'Budgets trigger management alerts; they do not grant execution or deployment permission.',
          )}
        </p>
        {error && <ReadError code={error} t={t} />}
        {editing && (
          <BudgetForm
            t={t}
            budget={editing}
            busy={busy}
            onSave={async (value) => {
              if (await onBudget(value)) setEditing(null);
            }}
          />
        )}
        <Button variant="ghost" onClick={() => setEditing(null)}>
          {t('Cancel')}
        </Button>
      </Dialog>
    </section>
  );
}

function BudgetForm({
  t,
  budget,
  busy,
  onSave,
}: {
  t: Translate;
  budget: Budget;
  busy: boolean;
  onSave: (value: Budget) => void;
}) {
  const [dev, setDev] = useState(budget.development_tokens?.toString() ?? '');
  const [runtime, setRuntime] = useState(
    budget.runtime_tokens?.toString() ?? '',
  );
  const [currency, setCurrency] = useState(budget.currency ?? 'KRW');
  const [amount, setAmount] = useState(
    budget.amount_minor == null
      ? ''
      : String(budget.amount_minor / (currency === 'KRW' ? 1 : 100)),
  );
  return (
    <form
      className="stack wb-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          version: budget.version,
          development_tokens: dev ? Number(dev) : null,
          runtime_tokens: runtime ? Number(runtime) : null,
          amount_minor: amount
            ? Math.round(Number(amount) * (currency === 'KRW' ? 1 : 100))
            : null,
          currency,
        });
      }}
    >
      <label>
        {t('Development token budget')}
        <Input
          type="number"
          min="1"
          max={10 ** 12}
          value={dev}
          onChange={(e) => setDev(e.target.value)}
        />
      </label>
      <label>
        {t('Runtime token budget')}
        <Input
          type="number"
          min="1"
          max={10 ** 12}
          value={runtime}
          onChange={(e) => setRuntime(e.target.value)}
        />
      </label>
      <label>
        {t('Monthly cost budget')}
        <Input
          type="number"
          min={currency === 'KRW' ? 1 : 0.01}
          step={currency === 'KRW' ? 1 : 0.01}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </label>
      <label>
        {t('Currency')}
        <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
          <option>KRW</option>
          <option>USD</option>
        </select>
      </label>
      <Button type="submit" disabled={busy}>
        {t('Save')}
      </Button>
    </form>
  );
}

function MaintenanceForm({
  t,
  item,
  busy,
  onSave,
  onCancel,
}: {
  t: Translate;
  item: Maintenance | null;
  busy: boolean;
  onSave: (body: S['MaintenanceInput']) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(item?.title ?? '');
  const [notes, setNotes] = useState(item?.notes ?? '');
  const [owner, setOwner] = useState(item?.owner ?? '');
  const [due, setDue] = useState(item?.due_on ?? '');
  const [target, setTarget] = useState(item?.target_revision ?? '');
  const [state, setState] = useState<S['MaintenanceInput']['state']>(
    item?.state === 'verified' ? 'planned' : (item?.state ?? 'open'),
  );
  return (
    <form
      className="stack wb-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          title,
          notes,
          owner,
          due_on: due || null,
          target_revision: target || null,
          state,
          task_id: item?.task_id ?? null,
          version: item?.version ?? 0,
        });
      }}
    >
      <label>
        {t('Problem or patch title')}
        <Input
          required
          maxLength={200}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <label>
        {t('Maintenance notes')}
        <textarea
          maxLength={4000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      <label>
        {t('Maintenance owner')}
        <Input
          maxLength={120}
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
        />
      </label>
      <label>
        {t('Target date')}
        <Input
          type="date"
          value={due}
          onChange={(e) => setDue(e.target.value)}
        />
      </label>
      <label>
        {t('Target revision')}
        <Input
          pattern="[0-9a-f]{40}"
          maxLength={40}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        />
      </label>
      <label>
        {t('Maintenance state')}
        <select
          value={state}
          onChange={(e) =>
            setState(e.target.value as S['MaintenanceInput']['state'])
          }
        >
          <option value="open">{t('Open')}</option>
          <option value="planned">{t('Planned')}</option>
          <option value="cancelled">{t('Cancelled')}</option>
        </select>
      </label>
      <div className="actions">
        <Button type="submit" disabled={busy}>
          {t('Save')}
        </Button>
        <Button type="button" onClick={onCancel}>
          {t('Cancel')}
        </Button>
      </div>
    </form>
  );
}

export function WorkbenchPlatform({
  t,
  navigate,
  startTask,
}: {
  t: Translate;
  navigate: (page: 'templates' | 'instructions' | 'monitoring') => void;
  startTask: StartWorkbenchTask;
}) {
  const [refresh, setRefresh] = useState(0);
  const { data, error, loading } = useResource<S['PlatformOut']>(
    '/workbench/platform',
    refresh,
  );
  const { services, failed } = useServices();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const start = async (
    purpose: 'development' | 'inspection' | 'deployment' | 'recovery',
  ) => {
    setBusy(true);
    setActionError(null);
    try {
      await startTask(
        { area: 'platform', purpose },
        t(
          purpose === 'development'
            ? 'Develop the launcher'
            : purpose === 'deployment'
              ? 'Prepare a release'
              : purpose === 'recovery'
                ? 'Plan recovery'
                : 'Inspect services',
        ),
        purpose === 'development'
          ? 'Review the launcher and shared platform contracts. Ask for the requested change, inspect affected consumers and propose implementation and validation.'
          : `Read the applicable repository operations instructions. Prepare an ${purpose} plan with the exact environment, revision, checks and recovery procedure. Do not publish, merge, deploy, restart services or roll back without my explicit authorization.`,
      );
    } catch (e) {
      setActionError(e instanceof ApiError ? e.code : 'request_failed');
    } finally {
      setBusy(false);
    }
  };
  return (
    <PageLayout
      title={t('Platform management')}
      description={t(
        'Manage launcher development, source control, harness and service delivery.',
      )}
      actions={
        <Button
          variant="ghost"
          aria-label={t('Refresh')}
          onClick={() => setRefresh((v) => v + 1)}
        >
          <RefreshCw size={16} />
        </Button>
      }
    >
      <div className="actions">
        <Button onClick={() => navigate('instructions')}>
          {t('Instructions and skills')}
        </Button>
        <Button onClick={() => navigate('templates')}>
          {t('Task templates')}
        </Button>
        <Button onClick={() => navigate('monitoring')}>
          {t('Monitoring')}
        </Button>
      </div>
      <section className="wb-panel">
        <h2>{t('Platform work')}</h2>
        <div className="actions">
          <Button disabled={busy} onClick={() => void start('development')}>
            {t('Develop the launcher')}
          </Button>
          <Button disabled={busy} onClick={() => void start('inspection')}>
            {t('Inspect services')}
          </Button>
          <Button disabled={busy} onClick={() => void start('deployment')}>
            {t('Prepare a release')}
          </Button>
          <Button disabled={busy} onClick={() => void start('recovery')}>
            {t('Plan recovery')}
          </Button>
        </div>
      </section>
      {actionError && <ReadError code={actionError} t={t} />}
      {error && <ReadError code={error} t={t} />}
      {loading && <p role="status">{t('Loading source status')}</p>}
      {data && (
        <>
          <section className="wb-panel">
            <h2>{t('Local source')}</h2>
            {error && (
              <p className="muted">{t('Current state not verified')}</p>
            )}
            <p>
              MIY Workbench · {t('Installed revision')}:{' '}
              <Revision value={data.workbench_release?.source_revision} t={t} />{' '}
              {data.workbench_release?.source_dirty && t('Uncommitted changes')}
            </p>
            {data.workbench_release && (
              <p>
                <code>{data.workbench_release.digest}</code>
              </p>
            )}
            {data.git ? (
              <>
                <dl className="wb-facts">
                  <div>
                    <dt>{t('Branch')}</dt>
                    <dd>{data.git.branch ?? t('Detached HEAD')}</dd>
                  </div>
                  <div>
                    <dt>HEAD</dt>
                    <dd>
                      <Revision value={data.git.head} t={t} />
                    </dd>
                  </div>
                  <div>
                    <dt>{t('Changed files')}</dt>
                    <dd>{data.git.changed}</dd>
                  </div>
                  <div>
                    <dt>{t('Conflicts')}</dt>
                    <dd>{data.git.conflicts}</dd>
                  </div>
                </dl>
                <p className="muted">
                  {t('Local tracking refs are not automatically fetched.')}
                </p>
              </>
            ) : (
              <p>{t('Not verified')}</p>
            )}
            <h3>{t('Recent commits')}</h3>
            <ul className="wb-commits">
              {data.commits.map((commit) => (
                <li key={commit.revision}>
                  <Revision value={commit.revision} t={t} /> {commit.subject}
                </li>
              ))}
            </ul>
            <h3>{t('Worktrees')}</h3>
            {data.worktrees.map((root) => (
              <p key={root}>
                <code>{root}</code>
              </p>
            ))}
          </section>
          <section className="wb-panel">
            <h2>GitLab</h2>
            <Connection
              state={error ? 'unavailable' : data.gitlab.state}
              stale={!!error || data.gitlab.stale}
              checkedAt={data.gitlab.checked_at}
              t={t}
            />
            {(
              [
                ['branches', 'Branches'],
                ['merge_requests', 'Merge requests'],
                ['pipelines', 'CI pipelines'],
              ] as const
            ).map(([key, label]) => (
              <div key={key}>
                <h3>{t(label)}</h3>
                <ul className="wb-commits">
                  {data.gitlab[key]?.map((item) => (
                    <li key={`${item.id ?? item.name}`}>
                      {item.url ? (
                        <a href={item.url} target="_blank" rel="noreferrer">
                          {item.name}
                        </a>
                      ) : (
                        item.name
                      )}{' '}
                      ·{' '}
                      {error || data.gitlab.stale
                        ? t('Not verified')
                        : item.status}{' '}
                      <Revision value={item.revision} t={t} />
                    </li>
                  ))}
                </ul>
                {!data.gitlab[key]?.length && (
                  <p className="muted">
                    {t(
                      !error && data.gitlab.state === 'ready'
                        ? 'No entries'
                        : 'Not verified',
                    )}
                  </p>
                )}
              </div>
            ))}
          </section>
        </>
      )}
      <section className="wb-panel">
        <h2>{t('Services')}</h2>
        {failed && <p role="alert">{t('Service status unavailable')}</p>}
        <div className="wb-catalog">
          {services.map((service) => (
            <div className="wb-service" key={service.id}>
              <strong>{service.name}</strong>
              <p>
                {service.environment} ·{' '}
                {failed || service.stale ? t('Not verified') : service.status}
              </p>
              <Revision value={service.version} t={t} />
              <small>
                {service.checked_at
                  ? new Date(service.checked_at).toLocaleString()
                  : t('Not verified')}
              </small>
            </div>
          ))}
        </div>
        <p className="muted">
          {t(
            'Service health and app functional verification are separate checks.',
          )}
        </p>
      </section>
    </PageLayout>
  );
}
