import { useEffect, useRef, useState } from 'react';
import { Button, Input } from '@miy/ui';
import { ExternalLink } from 'lucide-react';
import { api, ApiError, record, type Task } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';
import type { StartWorkbenchTask } from './workbench';

type S = components['schemas'];
export type Workspace = S['WorkspaceOut'];
type WorkspaceList = S['WorkspaceList'];
type Project = S['ProjectOut'];
type Action = 'stop' | 'resume' | 'refresh' | 'integrate' | 'cleanup';
type TaskProps = {
  t: Translate;
  tasks: Task[];
  openTask: (id: string) => void;
  startTask: StartWorkbenchTask;
};
const environmentLabels: Record<string, Copy> = {
  preparing: 'Environment preparing',
  ready: 'Environment ready',
  stopped: 'Environment stopped',
  stopping: 'Environment stopping',
  cleanup_pending: 'Environment cleanup pending',
  cleaned: 'Environment cleaned',
  error: 'Environment needs attention',
};
const previewLabels: Record<string, Copy> = {
  unconfigured: 'App runtime not configured',
  pending: 'App build pending',
  preparing: 'App build running',
  building: 'App build running',
  deploying: 'App build running',
  ready: 'App runtime ready',
  stopped: 'App runtime stopped',
  failed: 'App refresh failed',
  blocked: 'App refresh failed',
  unknown: 'Current state not verified',
};
const integrationLabels: Record<string, Copy> = {
  not_requested: 'Development integration not requested',
  reviewing: 'Development review in progress',
  blocked: 'Development integration blocked',
  unknown: 'Integration state unknown',
  merged: 'Merged; development app update pending',
  updating: 'Merged; development app update pending',
  dev_ready: 'Development app verified',
  succeeded: 'Development applied; cleanup pending',
  cleanup_pending: 'Development applied; cleanup pending',
  completed: 'Development applied and environment cleaned',
};
const cleanupLabels: Record<string, Copy> = {
  not_requested: 'Cleanup not requested',
  pending: 'Cleanup in progress',
  cleaning: 'Cleanup in progress',
  cleaned: 'Environment cleaned',
  completed: 'Environment cleaned',
  blocked: 'Cleanup needs attention',
  failed: 'Cleanup needs attention',
  cleanup_pending: 'Cleanup needs attention',
};
const actionLabels: Record<Action, Copy> = {
  stop: 'Stop environment',
  resume: 'Resume environment',
  refresh: 'Refresh app build',
  integrate: 'Apply to development',
  cleanup: 'Clean up environment',
};

function knownLink(value: string | null | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (
      !['https:', 'http:'].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.hash
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}

export function workspaceQuery(id: string) {
  const params = new URLSearchParams(window.location.search);
  params.set('environment', id);
  window.history.replaceState(null, '', `?${params}`);
}

export function createWorkspace(projectId: string, title?: string) {
  return workspaceRequest(
    `/workbench/projects/${encodeURIComponent(projectId)}/workspaces`,
    {
      operation_id: crypto.randomUUID(),
      ...(title ? { title } : {}),
      profile: 'app',
      auto_refresh: true,
    },
  );
}

async function workspaceRequest(path: string, body: unknown) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 30_000);
  try {
    return await api<Workspace>(path, body, 'POST', controller.signal);
  } finally {
    window.clearTimeout(timer);
  }
}

export function ProjectWorkspaces({
  project,
  ...props
}: TaskProps & { project: Project }) {
  return <ProjectEnvironments key={project.id} project={project} {...props} />;
}

function ProjectEnvironments({
  project,
  t,
  tasks,
  openTask,
  startTask,
}: TaskProps & { project: Project }) {
  const path = `/workbench/projects/${encodeURIComponent(project.id)}/workspaces`;
  const [list, setList] = useState<WorkspaceList | null>(null);
  const [selected, setSelected] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get('environment'),
  );
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState(project.title);
  const [busy, setBusy] = useState(false);
  const pending = useRef<string | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void api<WorkspaceList>(path, undefined, 'GET', controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        if (
          result.items.some(
            (item) =>
              item.project_id !== project.id || item.app_id !== project.app_id,
          )
        )
          throw new ApiError('workspace_changed');
        setList(result);
        setError(null);
        const existing = pending.current
          ? result.items.find((item) =>
              item.operations.some(
                (operation) => operation.operation_id === pending.current,
              ),
            )
          : null;
        if (existing) {
          pending.current = null;
          setCreating(false);
          setSelected(existing.id);
          workspaceQuery(existing.id);
        } else
          setSelected((current) =>
            current && result.items.some((item) => item.id === current)
              ? current
              : (result.items[0]?.id ?? null),
          );
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(reason instanceof ApiError ? reason.code : 'request_failed');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, refresh]);
  const create = async () => {
    if (busy || pending.current || !list?.available || error) return;
    const operationId = crypto.randomUUID();
    pending.current = operationId;
    setBusy(true);
    setError(null);
    try {
      const result = await workspaceRequest(path, {
        operation_id: operationId,
        title,
        profile: 'app',
        auto_refresh: true,
      });
      if (!mounted.current) return;
      if (result.project_id !== project.id || result.app_id !== project.app_id)
        throw new ApiError('workspace_changed');
      pending.current = null;
      setSelected(result.id);
      workspaceQuery(result.id);
      setCreating(false);
      setRefresh((value) => value + 1);
    } catch (reason) {
      if (!mounted.current) return;
      if (
        reason instanceof ApiError &&
        reason.status &&
        reason.status >= 400 &&
        reason.status < 500
      )
        pending.current = null;
      setError(reason instanceof ApiError ? reason.code : 'request_failed');
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <section
      className="wb-environments"
      aria-label={t('Development environments')}
    >
      <div className="wb-heading">
        <h3>{t('Development environments')}</h3>
        <div className="actions">
          <Button
            disabled={
              busy ||
              loading ||
              !!pending.current ||
              !list?.available ||
              !!error
            }
            onClick={() => setCreating((value) => !value)}
          >
            {t('New development environment')}
          </Button>
          <Button
            disabled={busy}
            variant="ghost"
            onClick={() => setRefresh((value) => value + 1)}
          >
            {t('Check operation state')}
          </Button>
        </div>
      </div>
      {loading && <p role="status">{t('Loading development environments')}</p>}
      {error && <p role="alert">{t(errorCopy(error))}</p>}
      {pending.current && !busy && (
        <p role="status">
          {t(
            'The response was lost. Check the existing operation before requesting another action.',
          )}
        </p>
      )}
      {list && !list.available && (
        <p>
          {t(
            'An administrator must connect the MIY development environment before starting this work.',
          )}
        </p>
      )}
      {creating && (
        <form
          className="wb-form"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <label>
            {t('Environment name')}
            <Input
              value={title}
              required
              maxLength={200}
              disabled={busy || !!pending.current}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <Button type="submit" disabled={busy || !!pending.current || !!error}>
            {t('Prepare environment')}
          </Button>
        </form>
      )}
      {!!list?.items.length && (
        <label>
          {t('Choose a development environment')}
          <select
            value={selected ?? ''}
            onChange={(event) => {
              setSelected(event.target.value);
              workspaceQuery(event.target.value);
            }}
          >
            {list.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title} ·{' '}
                {t(
                  environmentLabels[item.state] ??
                    'Environment needs attention',
                )}
              </option>
            ))}
          </select>
        </label>
      )}
      {list?.available && !list.items.length && (
        <p className="muted">{t('No development environments yet.')}</p>
      )}
      {selected && list?.items.some((item) => item.id === selected) && (
        <WorkspacePanel
          key={selected}
          id={selected}
          project={project}
          t={t}
          tasks={tasks}
          openTask={openTask}
          startTask={startTask}
          onChanged={() => setRefresh((value) => value + 1)}
        />
      )}
    </section>
  );
}

export function WorkspacePanel({
  id,
  project,
  t,
  tasks,
  openTask,
  startTask,
  onChanged,
  compact = false,
}: TaskProps & {
  id: string;
  project?: Project;
  onChanged?: () => void;
  compact?: boolean;
}) {
  const path = `/workbench/workspaces/${encodeURIComponent(id)}`;
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<
    'integrate' | 'cleanup' | null
  >(null);
  const [refresh, setRefresh] = useState(0);
  const mounted = useRef(false);
  const request = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden')
        setRefresh((value) => value + 1);
    }, 10_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void api<Workspace>(path, undefined, 'GET', controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        if (
          result.id !== id ||
          (project &&
            (result.project_id !== project.id ||
              result.app_id !== project.app_id))
        )
          throw new ApiError('workspace_changed');
        setWorkspace((current) =>
          current && current.version > result.version ? current : result,
        );
        setError(null);
        if (
          unknown &&
          result.operations.some(
            (operation) => operation.operation_id === unknown,
          )
        )
          setUnknown(null);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(reason instanceof ApiError ? reason.code : 'request_failed');
      });
    return () => controller.abort();
  }, [path, id, project?.id, project?.app_id, refresh]);
  const unresolved = !!workspace?.operations.some(
    (operation) =>
      operation.unknown ||
      ['pending', 'running', 'unknown'].includes(operation.state),
  );
  const waiting = workspace?.operations.find(
    (operation) =>
      operation.state === 'waiting' &&
      operation.source_revision === workspace.source_revision,
  );
  const staleWaiting = workspace?.operations.some(
    (operation) =>
      operation.state === 'waiting' &&
      operation.source_revision !== workspace.source_revision,
  );
  const continuedAction =
    waiting?.kind === 'auto_refresh' ? 'refresh' : waiting?.kind;
  const unavailable = busy || !!error || !!unknown || unresolved || !workspace;
  const mutationUnavailable = unavailable || !!waiting;
  const waitingReview =
    waiting?.kind === 'integrate' &&
    workspace?.integration.state === 'reviewing' &&
    workspace.integration.source_revision === workspace.source_revision;
  const lifecycleUnavailable = unavailable || (!!waiting && !waitingReview);
  const continuationUnavailable =
    unavailable ||
    (['integrate', 'refresh'].includes(continuedAction ?? '') &&
      workspace?.state !== 'ready' &&
      workspace?.integration.state !== 'succeeded');
  const mutate = async (action: Action, continuation?: string) => {
    if (request.current || unavailable || !workspace) return;
    if (continuation && continuationUnavailable) return;
    if (
      waiting &&
      continuation !== waiting.operation_id &&
      !(['stop', 'resume'].includes(action) && waitingReview)
    )
      return;
    request.current = true;
    const operationId = continuation ?? crypto.randomUUID();
    setBusy(true);
    setError(null);
    setConfirmation(null);
    try {
      const next = await workspaceRequest(`${path}/${action}`, {
        operation_id: operationId,
        expected_version: workspace.version,
      });
      if (!mounted.current) return;
      if (
        next.id !== workspace.id ||
        next.project_id !== workspace.project_id ||
        next.app_id !== workspace.app_id
      )
        throw new ApiError('workspace_changed');
      setWorkspace((current) =>
        current && current.version > next.version ? current : next,
      );
      onChanged?.();
    } catch (reason) {
      if (!mounted.current) return;
      if (
        !(
          reason instanceof ApiError &&
          reason.status &&
          reason.status >= 400 &&
          reason.status < 500
        )
      )
        setUnknown(operationId);
      setError(reason instanceof ApiError ? reason.code : 'request_failed');
    } finally {
      request.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  if (!workspace)
    return (
      <div>
        <p role={error ? 'alert' : 'status'}>
          {error ? t(errorCopy(error)) : t('Loading development environments')}
        </p>
        {error && (
          <Button onClick={() => setRefresh((value) => value + 1)}>
            {t('Check operation state')}
          </Button>
        )}
      </div>
    );
  const openURL =
    !error &&
    workspace.preview.state === 'ready' &&
    workspace.preview.runtime_revision
      ? knownLink(workspace.preview.portal_url)
      : null;
  const mrURL = knownLink(workspace.integration.mr_url);
  const changed =
    !!workspace.source_revision &&
    workspace.source_revision !== workspace.preview.runtime_revision;
  const writable = workspace.state === 'ready' && workspace.admission_open;
  const linkedTasks = tasks.filter(
    (task) => record(task.context).workspace_id === workspace.id,
  );
  const devVerified =
    !!workspace.integration.merged_revision &&
    workspace.integration.dev_runtime_revision ===
      workspace.integration.merged_revision;
  const integrationChanged =
    !!workspace.integration.source_revision &&
    workspace.integration.source_revision !== workspace.source_revision;
  const integrationState = integrationChanged
    ? 'blocked'
    : ['succeeded', 'dev_ready', 'cleanup_pending', 'completed'].includes(
          workspace.integration.state,
        )
      ? !devVerified
        ? 'merged'
        : workspace.state === 'cleaned' && workspace.cleanup.state === 'cleaned'
          ? 'completed'
          : 'cleanup_pending'
      : workspace.integration.state;
  const beginSession = (purpose: 'development' | 'registration') => {
    if (request.current || unavailable || !writable) return;
    request.current = true;
    setBusy(true);
    void startTask(
      {
        area: 'studio',
        purpose,
        project_id: workspace.project_id,
        app_id: workspace.app_id,
        workspace_id: workspace.id,
      },
      project?.title ?? workspace.title,
      purpose === 'registration'
        ? "Inspect this registration Task's committed app source in the selected environment. Use miy_app_registration context and prepare a personal, inactive development registration plan. MIY owner authorization and explicit implementation approval are required. Registration alone does not verify app execution or deployment."
        : `${project?.summary ?? ''}\nContinue this app in the selected managed development environment. Read its current source and public platform contracts, then ask for the requested change and prepare a plan. Reuse existing valid checks for unchanged inputs. The server owns source checkpoints, runtime refresh and development integration.`,
    )
      .catch((reason) => {
        if (mounted.current)
          setError(reason instanceof ApiError ? reason.code : 'request_failed');
      })
      .finally(() => {
        request.current = false;
        if (mounted.current) setBusy(false);
      });
  };
  const content = (
    <section className="wb-workspace" aria-label={t('Workspace details')}>
      <div className="wb-heading">
        <div>
          <strong>{workspace.title}</strong>
          <p role="status">
            {t(
              environmentLabels[workspace.state] ??
                'Environment needs attention',
            )}
          </p>
        </div>
        {openURL && (
          <a href={openURL} target="_blank" rel="noopener noreferrer">
            {t('Open app in new tab')} <ExternalLink size={13} />
          </a>
        )}
      </div>
      <p className="muted">
        {t('The same environment is shared by this work’s sessions.')}
      </p>
      {error && <p role="alert">{t(errorCopy(error))}</p>}
      {(unknown ||
        workspace.operations.some((operation) => operation.unknown)) && (
        <p role="status">
          {t(
            'The response was lost. Check the existing operation before requesting another action.',
          )}
        </p>
      )}
      {workspace.failure_code && (
        <p role="alert">{t(errorCopy(workspace.failure_code))}</p>
      )}
      {staleWaiting && (
        <p role="status">
          {t(
            'The source has changed. Start a new action to use the current version.',
          )}
        </p>
      )}
      <p role="status">
        {t(
          previewLabels[workspace.preview.state] ??
            'App runtime not configured',
        )}
      </p>
      {workspace.preview.failure_code && (
        <p role="alert">{t(errorCopy(workspace.preview.failure_code))}</p>
      )}
      {!openURL && (
        <p className="muted">
          {t('The app link is available after its runtime is verified.')}
        </p>
      )}
      {changed && (
        <p>
          {t(
            'Saved changes are not running yet. Refresh the app build after finishing your changes.',
          )}
        </p>
      )}
      <div className="actions">
        <Button
          disabled={unavailable || !writable}
          onClick={() => beginSession('development')}
        >
          {t('Start a development session')}
        </Button>
        <Button
          disabled={unavailable || !writable}
          onClick={() => beginSession('registration')}
        >
          {t('New registration task')}
        </Button>
        <Button
          disabled={mutationUnavailable || workspace.state !== 'ready'}
          onClick={() => void mutate('refresh')}
        >
          {t('Refresh app build')}
        </Button>
        <Button
          disabled={
            lifecycleUnavailable ||
            ['cleaned', 'stopped', 'preparing'].includes(workspace.state)
          }
          onClick={() => void mutate('stop')}
        >
          {t('Stop environment')}
        </Button>
        <Button
          disabled={
            lifecycleUnavailable ||
            !['stopped', 'error'].includes(workspace.state)
          }
          onClick={() => void mutate('resume')}
        >
          {t('Resume environment')}
        </Button>
        <Button
          disabled={
            mutationUnavailable ||
            !['ready', 'cleanup_pending'].includes(workspace.state)
          }
          onClick={() => setConfirmation('integrate')}
        >
          {t('Apply to development')}
        </Button>
        <Button
          disabled={
            mutationUnavailable ||
            workspace.state === 'cleaned' ||
            workspace.integration.state !== 'succeeded'
          }
          onClick={() => setConfirmation('cleanup')}
        >
          {t('Clean up environment')}
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => setRefresh((value) => value + 1)}
        >
          {t('Check operation state')}
        </Button>
        {waiting &&
          continuedAction &&
          record(waiting).continuable === true &&
          Object.hasOwn(actionLabels, continuedAction) && (
            <Button
              disabled={continuationUnavailable}
              onClick={() =>
                void mutate(continuedAction as Action, waiting.operation_id)
              }
            >
              {t('Continue operation')}
            </Button>
          )}
      </div>
      {confirmation && (
        <section
          className="request-panel"
          aria-label={t('Confirm development action')}
        >
          <h4>
            {t(
              confirmation === 'integrate'
                ? 'Apply this work to development?'
                : 'Clean up this development environment?',
            )}
          </h4>
          <p>
            {t(
              confirmation === 'integrate'
                ? 'Review and checks precede the dev merge, development app update and owned environment cleanup. Production delivery is separate.'
                : 'The server checks merge evidence and active sessions before cleaning up this work’s temporary resources.',
            )}
          </p>
          <p>
            <code>{workspace.branch}</code>
          </p>
          <Button
            disabled={unavailable}
            onClick={() => void mutate(confirmation)}
          >
            {t(actionLabels[confirmation])}
          </Button>
          <Button
            disabled={busy}
            variant="ghost"
            onClick={() => setConfirmation(null)}
          >
            {t('Cancel')}
          </Button>
        </section>
      )}
      <p role="status">
        {t(integrationLabels[integrationState] ?? 'Integration state unknown')}
      </p>
      {workspace.integration.failure_code && (
        <p role="alert">{t(errorCopy(workspace.integration.failure_code))}</p>
      )}
      {mrURL && (
        <a href={mrURL} target="_blank" rel="noopener noreferrer">
          {t('Review merge request')} <ExternalLink size={13} />
        </a>
      )}
      <p role="status">
        {t(cleanupLabels[workspace.cleanup.state] ?? 'Cleanup needs attention')}
      </p>
      {workspace.cleanup.failure_code && (
        <p role="alert">{t(errorCopy(workspace.cleanup.failure_code))}</p>
      )}
      <details>
        <summary>{t('Workspace details')}</summary>
        <dl className="wb-facts">
          <div>
            <dt>{t('Branch')}</dt>
            <dd>
              <code>{workspace.branch}</code>
            </dd>
          </div>
          <div>
            <dt>{t('Saved source')}</dt>
            <dd>
              <code>
                {workspace.source_revision?.slice(0, 12) ?? t('Not verified')}
              </code>
            </dd>
          </div>
          <div>
            <dt>{t('Running app source')}</dt>
            <dd>
              <code>
                {workspace.preview.runtime_revision?.slice(0, 12) ??
                  t('Not verified')}
              </code>
            </dd>
          </div>
          <div>
            <dt>{t('Development app source')}</dt>
            <dd>
              <code>
                {workspace.integration.dev_runtime_revision?.slice(0, 12) ??
                  t('Not verified')}
              </code>
            </dd>
          </div>
        </dl>
        <h4>{t('Operation history')}</h4>
        <ul>
          {workspace.operations.map((operation) => (
            <li key={operation.operation_id}>
              {t(
                actionLabels[operation.kind as Action] ?? 'Prepare environment',
              )}{' '}
              · {operation.state}
              {operation.failure_code && (
                <>
                  {' '}
                  · <code>{operation.failure_code}</code>
                </>
              )}
            </li>
          ))}
        </ul>
      </details>
      {!!linkedTasks.length && (
        <div className="wb-work-list" aria-label={t('Related work')}>
          {linkedTasks.map((task) => (
            <button key={task.id} onClick={() => openTask(task.id)}>
              {task.title}
              <small>
                {task.stage} · {task.status}
              </small>
            </button>
          ))}
        </div>
      )}
    </section>
  );
  return compact ? (
    <div className="task-environment">
      <div className="wb-heading">
        <div>
          <strong>{workspace.title}</strong> · <code>{workspace.branch}</code>
          <p role="status">
            {t(
              environmentLabels[workspace.state] ??
                'Environment needs attention',
            )}
          </p>
        </div>
        {openURL && (
          <a href={openURL} target="_blank" rel="noopener noreferrer">
            {t('Open app in new tab')} <ExternalLink size={13} />
          </a>
        )}
      </div>
      <details>
        <summary>{t('Workspace details')}</summary>
        {content}
      </details>
    </div>
  ) : (
    content
  );
}
