import { Button } from '@miy/ui';
import { useLayoutEffect, useRef, useState } from 'react';
import { api, ApiError, record } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';

type S = components['schemas'];
type Observation = S['ProjectExecutionReadinessOut'];
type Props = {
  project: S['ProjectOut'];
  source?: S['AppDescriptor'];
  busy: boolean;
  registrationAvailable: boolean;
  scope: string;
  onStart: (purpose: 'development' | 'registration') => Promise<void>;
  t: Translate;
};
const states: Record<Observation['state'], Copy> = {
  reachable: 'Execution environment connection confirmed.',
  unconfigured: 'Execution environment connection is not configured.',
  unavailable: 'Execution environment connection could not be confirmed.',
  changed:
    'Source or execution environment changed. Refresh before continuing.',
  unsupported: 'The execution environment needs the supported version.',
  denied: 'The selected app source is no longer available.',
};

export function ProjectTaskActions(props: Props) {
  const { project, source, scope } = props;
  return (
    <Actions
      key={`${project.id}:${project.app_id}:${source?.source_version ?? 0}:${source?.source_status}:${source?.execution_status}:${scope}`}
      {...props}
    />
  );
}

function Actions({
  project,
  source,
  busy,
  registrationAvailable,
  onStart,
  t,
}: Props) {
  const independent = source?.discovery === 'source';
  const needsExecutor =
    independent &&
    source.source_status === 'ready' &&
    source.execution_status !== 'configured';
  const [checking, setChecking] = useState(false);
  const [observation, setObservation] = useState<Observation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<{
    controller: AbortController;
    deadline: number;
  } | null>(null);
  const mounted = useRef(false);
  const starting = useRef(false);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const request = active.current;
      active.current = null;
      if (request) {
        window.clearTimeout(request.deadline);
        request.controller.abort();
      }
    };
  }, []);
  const check = async (purpose?: 'development' | 'registration') => {
    if (busy || starting.current || active.current) return;
    setError(null);
    if (!independent) {
      if (!purpose) return;
      starting.current = true;
      try {
        await onStart(purpose);
      } catch (reason) {
        if (mounted.current)
          setError(reason instanceof ApiError ? reason.code : 'request_failed');
      } finally {
        starting.current = false;
      }
      return;
    }
    const controller = new AbortController();
    const deadline = window.setTimeout(() => {
      if (active.current?.controller !== controller) return;
      active.current = null;
      controller.abort();
      setChecking(false);
      setError('request_failed');
    }, 30_000);
    active.current = { controller, deadline };
    setChecking(true);
    setObservation(null);
    try {
      const value = record(
        await api<unknown>(
          `/workbench/projects/${encodeURIComponent(project.id)}/execution-readiness`,
          undefined,
          'GET',
          controller.signal,
        ),
      );
      if (
        !mounted.current ||
        active.current?.controller !== controller ||
        controller.signal.aborted
      )
        return;
      if (
        value.project_id !== project.id ||
        typeof value.state !== 'string' ||
        !Object.hasOwn(states, value.state) ||
        typeof value.checked_at !== 'string' ||
        value.checked_at.length > 64 ||
        !Number.isFinite(Date.parse(value.checked_at)) ||
        (value.failure_code !== null &&
          (typeof value.failure_code !== 'string' ||
            value.failure_code.length > 80)) ||
        (value.state === 'reachable' &&
          (value.app_id !== project.app_id ||
            value.source_version !== source.source_version ||
            value.failure_code !== null))
      )
        throw new ApiError('app_executor_changed');
      const result = value as Observation;
      window.clearTimeout(deadline);
      setObservation(result);
      if (purpose && result.state === 'reachable') {
        starting.current = true;
        await onStart(purpose);
      }
    } catch (reason) {
      if (
        mounted.current &&
        active.current?.controller === controller &&
        !controller.signal.aborted
      )
        setError(reason instanceof ApiError ? reason.code : 'request_failed');
    } finally {
      window.clearTimeout(deadline);
      if (active.current?.controller === controller) {
        active.current = null;
        starting.current = false;
        if (mounted.current) setChecking(false);
      }
    }
  };
  return (
    <div className="stack">
      <div className="actions">
        <Button
          disabled={busy || checking || needsExecutor}
          onClick={() => void check('development')}
        >
          {t('Continue development')}
        </Button>
        {registrationAvailable &&
          independent &&
          source.source_status === 'ready' &&
          source.execution_status === 'configured' && (
            <Button
              disabled={busy || checking}
              onClick={() => void check('registration')}
            >
              {t('New registration task')}
            </Button>
          )}
        {independent && (
          <Button
            variant="ghost"
            disabled={busy || checking}
            onClick={() => void check()}
          >
            {t(
              checking
                ? 'Checking execution environment connection'
                : 'Check execution environment connection',
            )}
          </Button>
        )}
      </div>
      {checking && (
        <p role="status">{t('Checking execution environment connection')}</p>
      )}
      {error && <p role="alert">{t(errorCopy(error))}</p>}
      {observation && (
        <div role="status" className="muted">
          <p>{t(states[observation.state])}</p>
          {observation.failure_code && (
            <p>{t(errorCopy(observation.failure_code))}</p>
          )}
          <p>
            {t('Checked at')}:{' '}
            {new Date(observation.checked_at).toLocaleString(t.locale)}
          </p>
          <p>
            {t(
              'This checks connection, version and source binding. Permissions and sandbox policies are checked separately when work starts.',
            )}
          </p>
        </div>
      )}
    </div>
  );
}
