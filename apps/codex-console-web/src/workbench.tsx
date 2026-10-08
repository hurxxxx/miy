import { useEffect, useRef, useState } from 'react';
import { appIconForKey, Button, Input } from '@miy/ui';
import { Boxes, Code2, ExternalLink, Plus, RefreshCw } from 'lucide-react';
import { api, record, type Task } from './api';
import type { components } from './api.generated';
import { type Copy, type Translate, errorCopy, korean } from './i18n';
import { ApiError } from './api';
import { PageLayout, EmptyState } from './page-layout';
import { useServices } from './management';
import { SourcePrepare } from './source-prepare';
import { SourceRegistrationExport } from './source-registration-export';
import { SourceRegistrationStatus } from './source-registration-status';
import { ProjectTaskActions } from './project-task-actions';

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
    return () => window.clearInterval(timer);
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
  newTask,
}: {
  area: 'studio' | 'apps';
  t: Translate;
  tasks: Task[];
  openTask: (id: string) => void;
  startTask: StartWorkbenchTask;
  newTask: () => void;
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
  const [query, setQuery] = useState('');
  const [newProject, setNewProject] = useState(false);
  const [connectingSource, setConnectingSource] = useState(false);
  const [preparingSource, setPreparingSource] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const app = data?.items.find((item) => item.app_id === selected);
  const executorMissing =
    app?.discovery === 'source' &&
    app.source_status === 'ready' &&
    app.execution_status !== 'configured';
  const detailRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!app) return;
    detailRef.current?.focus({ preventScroll: true });
    detailRef.current?.scrollIntoView({ block: 'start' });
  }, [app?.app_id]);
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
  const filtered = (data?.items ?? []).filter((item) =>
    `${appTitle(item, t)} ${item.title} ${item.app_id} ${item.summary} ${(item.capabilities ?? []).join(' ')}`
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  return (
    <PageLayout
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
          <Button onClick={() => setConnectingSource((value) => !value)}>
            {t('Connect app source')}
          </Button>
          {area === 'studio' && (
            <>
              <Button onClick={newTask}>{t('New task')}</Button>
              <Button
                variant="primary"
                onClick={() => setNewProject(!newProject)}
              >
                <Plus size={16} />
                {t('New app project')}
              </Button>
            </>
          )}
        </>
      }
    >
      {error && <ReadError code={error} t={t} />}
      {runtime.error && <ReadError code={runtime.error} t={t} />}
      {actionError && <ReadError code={actionError} t={t} />}
      {loading && <p role="status">{t('Loading app catalog')}</p>}
      {data && (
        <>
          <p className="muted">
            {t('Development revision')}:{' '}
            <Revision value={data.source_revision} t={t} />{' '}
            {data.source_dirty && t('Uncommitted changes')}
            {error && <> · {t('Current state not verified')}</>}
          </p>
          {connectingSource && (
            <SourceBindingForm
              t={t}
              onSaved={(appId) => {
                setSelected(appId);
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
                  setRefresh((v) => v + 1);
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
          <label className="wb-search">
            {t('Find an app')}
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('Search purpose or capability')}
            />
          </label>
          {area === 'studio' && (
            <Button
              disabled={busy}
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
          <div className={`wb-app-layout${app ? ' has-selection' : ''}`}>
            <div className="wb-app-picker">
              <div
                className="wb-catalog"
                role="group"
                aria-label={t('App catalog')}
              >
                {filtered.map((item) => (
                  <button
                    key={item.app_id}
                    className={`wb-app ${selected === item.app_id ? 'selected' : ''}`}
                    aria-pressed={selected === item.app_id}
                    onClick={() => {
                      setSelected(item.app_id);
                      const params = new URLSearchParams(
                        window.location.search,
                      );
                      params.set('view', area);
                      params.set('app', item.app_id);
                      window.history.replaceState(null, '', `?${params}`);
                    }}
                  >
                    <AppIcon app={item} />
                    <strong>{appTitle(item, t)}</strong>
                    <small>{catalogText(item.summary, t)}</small>
                    <span>
                      {t(
                        item.source_status === 'ready'
                          ? 'Source available'
                          : 'Registered app',
                      )}
                    </span>
                  </button>
                ))}
              </div>
              {!filtered.length && (
                <EmptyState
                  icon={<Boxes />}
                  title={t('No matching apps')}
                  description={t(
                    'Search existing capabilities before starting a new app.',
                  )}
                />
              )}
            </div>
            {app && (
              <section
                className="wb-panel"
                ref={detailRef}
                tabIndex={-1}
                aria-label={t('Selected app')}
              >
                <div className="wb-heading">
                  <div>
                    <h2>{appTitle(app, t)}</h2>
                    <p>{catalogText(app.summary, t)}</p>
                  </div>
                  <div className="actions">
                    <Button
                      variant="primary"
                      disabled={busy || executorMissing}
                      onClick={() =>
                        void run(() =>
                          startTask(
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
                        {t('Open development app')} <ExternalLink size={13} />
                      </a>
                    )}
                  </div>
                </div>
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
                    {t('Preview configured; availability not verified')}
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
                    key={app.app_id}
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
                {area === 'apps' && (
                  <AppManagement
                    key={app.app_id}
                    app={app}
                    runtime={
                      runtime.data && runtime.error
                        ? { ...runtime.data, state: 'unavailable', stale: true }
                        : runtime.data
                    }
                    t={t}
                    refresh={refresh}
                    startTask={startTask}
                    openTask={openTask}
                    tasks={tasks}
                  />
                )}
                {app.discovery && app.discovery !== 'checkout' && (
                  <AppInstallations
                    key={app.app_id}
                    appId={app.app_id}
                    refresh={refresh}
                    t={t}
                    startTask={
                      app.source_status === 'ready' && !executorMissing
                        ? startTask
                        : undefined
                    }
                  />
                )}
                <h3>{t('Related work')}</h3>
                <div className="wb-work-list">
                  {tasks
                    .filter(
                      (task) => record(task.context).app_id === app.app_id,
                    )
                    .map((task) => (
                      <button key={task.id} onClick={() => openTask(task.id)}>
                        {task.title}
                        <small>
                          {task.stage} · {task.status}
                        </small>
                      </button>
                    ))}
                </div>
              </section>
            )}
          </div>
          {area === 'studio' && data.projects.length > 0 && (
            <section className="wb-panel">
              <h2>{t('App projects')}</h2>
              {data.projects.map((project) => {
                const projectApp = data.items.find(
                  (item) => item.app_id === project.app_id,
                );
                const needsExecutor =
                  projectApp?.discovery === 'source' &&
                  projectApp.source_status === 'ready' &&
                  projectApp.execution_status !== 'configured';
                return (
                  <div className="stack" key={project.id}>
                    <div className="wb-heading">
                      <div>
                        <strong>{project.title}</strong>
                        <p className="muted">{project.summary}</p>
                      </div>
                      <div className="actions">
                        {project.reuse_decision === 'new' && (
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
                      </div>
                    </div>
                    {needsExecutor && (
                      <p className="muted">
                        {t(
                          'Configure an isolated execution environment for this app.',
                        )}
                      </p>
                    )}
                    {preparingSource === project.id && (
                      <SourcePrepare
                        key={project.id}
                        projectId={project.id}
                        t={t}
                        onPrepared={() => setRefresh((value) => value + 1)}
                      />
                    )}
                    {projectApp?.discovery === 'source' &&
                      projectApp.source_status === 'ready' && (
                        <SourceRegistrationExport
                          key={project.id}
                          projectId={project.id}
                          t={t}
                        />
                      )}
                    {projectApp?.discovery === 'source' &&
                      projectApp.source_version > 0 && (
                        <SourceRegistrationStatus
                          projectId={project.id}
                          appId={project.app_id}
                          bindingVersion={projectApp.source_version}
                          t={t}
                        />
                      )}
                  </div>
                );
              })}
            </section>
          )}
          {area === 'apps' && runtime.error && (
            <ReadError code={runtime.error} t={t} />
          )}
        </>
      )}
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
  return (
    <form
      className="wb-panel stack"
      onSubmit={(e) => {
        e.preventDefault();
        onCreate({
          title,
          app_id: appId,
          summary,
          reuse_decision: decision,
          reuse_notes: notes,
        });
      }}
    >
      <h2>{t('New app project')}</h2>
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
            value={appId}
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
            value={appId}
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
          value={notes}
          maxLength={4000}
          required
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
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

function AppManagement({
  app,
  runtime,
  t,
  refresh,
  startTask,
  openTask,
  tasks,
}: {
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
      {error && <ReadError code={error} t={t} />}
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
          onBudget={(body) =>
            run(async () => {
              await api(`/workbench/apps/${app.app_id}/budget`, body, 'PUT');
            })
          }
        />
      )}
      <div className="wb-heading">
        <h3>{t('Maintenance and patches')}</h3>
        <Button onClick={() => setEdit(null)}>
          <Plus size={14} />
          {t('Register a problem')}
        </Button>
      </div>
      {patches.error && <ReadError code={patches.error} t={t} />}
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
              <Button variant="ghost" onClick={() => openTask(patch.task_id!)}>
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
  t,
  data,
  busy,
  onBudget,
}: {
  t: Translate;
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
