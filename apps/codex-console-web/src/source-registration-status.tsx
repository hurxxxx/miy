import { Button } from '@miy/ui';
import { useEffect, useRef, useState } from 'react';
import { api, ApiError, record } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';

type Observation = components['schemas']['SourceRegistrationStatusOut'];
type Props = {
  projectId: string;
  appId: string;
  bindingVersion: number;
  t: Translate;
};
const states: Record<Observation['state'], Copy> = {
  unregistered: 'No independent registration found at last check.',
  matching: 'Registration matches at last check.',
  different: 'Registration differs at last check.',
  collision: 'This app ID is registered to a different source.',
  unknown: 'Registration status could not be confirmed.',
};
const connections: Record<Observation['platform_state'], Copy> = {
  ready: 'Connected',
  unconfigured: 'Connection not configured',
  unavailable: 'Connection unavailable',
  unsupported: 'Integration update required',
  denied: 'Read access denied',
};
const revision = (value: unknown) =>
  typeof value === 'string' && /^[a-f0-9]{40}$/.test(value);
const digest = (value: unknown) =>
  typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value);

function checkedObservation(value: unknown, expected: Props): Observation {
  const data = record(value);
  if (
    data.project_id !== expected.projectId ||
    data.app_id !== expected.appId ||
    data.binding_version !== expected.bindingVersion ||
    !revision(data.source_revision) ||
    !digest(data.definition_digest) ||
    typeof data.state !== 'string' ||
    !Object.hasOwn(states, data.state) ||
    typeof data.platform_state !== 'string' ||
    !Object.hasOwn(connections, data.platform_state) ||
    (data.platform_checked_at !== null &&
      (typeof data.platform_checked_at !== 'string' ||
        data.platform_checked_at.length > 64 ||
        !Number.isFinite(Date.parse(data.platform_checked_at)))) ||
    (data.registered_source_revision !== null &&
      !revision(data.registered_source_revision)) ||
    (data.registered_definition_digest !== null &&
      !digest(data.registered_definition_digest))
  )
    throw new ApiError('request_failed');
  const compared = data.state === 'matching' || data.state === 'different';
  if (
    (data.state !== 'unknown' &&
      (data.platform_state !== 'ready' || !data.platform_checked_at)) ||
    (data.state === 'unregistered' &&
      (data.registered_source_revision !== null ||
        data.registered_definition_digest !== null)) ||
    (compared
      ? !data.registered_source_revision ||
        !data.registered_definition_digest ||
        data.definition_matches !==
          (data.definition_digest === data.registered_definition_digest) ||
        data.revision_matches !==
          (data.source_revision === data.registered_source_revision) ||
        (data.state === 'matching') !==
          (data.definition_matches && data.revision_matches)
      : data.definition_matches !== null || data.revision_matches !== null)
  )
    throw new ApiError('request_failed');
  return data as Observation;
}

/** A changed binding gets a new lifetime, including pending requests and results. */
export function SourceRegistrationStatus(props: Props) {
  return (
    <RegistrationCheck
      key={`${props.projectId}:${props.appId}:${props.bindingVersion}`}
      {...props}
    />
  );
}

function RegistrationCheck(props: Props) {
  const { projectId, appId, t } = props;
  const [observation, setObservation] = useState<Observation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = useRef<{
    controller: AbortController;
    deadline: number;
  } | null>(null);
  useEffect(
    () => () => {
      const request = active.current;
      active.current = null;
      if (request) {
        window.clearTimeout(request.deadline);
        request.controller.abort();
      }
    },
    [],
  );
  const check = async () => {
    if (active.current) return;
    const controller = new AbortController();
    const deadline = window.setTimeout(() => {
      if (active.current?.controller !== controller) return;
      active.current = null;
      controller.abort();
      setError('request_failed');
      setBusy(false);
    }, 30_000);
    active.current = { controller, deadline };
    setObservation(null);
    setError(null);
    setBusy(true);
    try {
      const result = await api<unknown>(
        `/workbench/projects/${encodeURIComponent(projectId)}/registration-status`,
        undefined,
        'GET',
        controller.signal,
      );
      if (
        active.current?.controller === controller &&
        !controller.signal.aborted
      )
        setObservation(checkedObservation(result, props));
    } catch (reason) {
      if (
        active.current?.controller === controller &&
        !controller.signal.aborted
      )
        setError(reason instanceof ApiError ? reason.code : 'request_failed');
    } finally {
      window.clearTimeout(deadline);
      if (active.current?.controller === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  };
  const compared =
    observation?.state === 'matching' || observation?.state === 'different';
  const matchLabel = (value: boolean | null) =>
    t(value === null ? 'Not compared' : value ? 'Matches' : 'Differs');
  return (
    <section className="stack" aria-label={t('Platform registration')}>
      <Button variant="secondary" disabled={busy} onClick={() => void check()}>
        {t(busy ? 'Checking registration status' : 'Check registration status')}
      </Button>
      <p className="muted">
        {t(
          'This compares registration at the reported check time. It does not verify installation readiness or deployment.',
        )}
      </p>
      {busy && <p role="status">{t('Checking registration status')}</p>}
      {!busy && !observation && !error && (
        <p>{t('No registration check yet.')}</p>
      )}
      {error && (
        <p role="alert" className="danger">
          {t('Registration status could not be confirmed.')}{' '}
          {t(errorCopy(error))}
        </p>
      )}
      {observation && (
        <>
          <p role="status">{t(states[observation.state])}</p>
          <p className="muted">
            {t(connections[observation.platform_state])}
            {observation.platform_checked_at && (
              <>
                {' · '}
                {t('Platform checked at')}
                {': '}
                <time dateTime={observation.platform_checked_at}>
                  {new Date(observation.platform_checked_at).toLocaleString(
                    t.locale,
                  )}
                </time>
              </>
            )}
          </p>
          <dl className="wb-facts">
            <div>
              <dt>{t('Source revision at check')}</dt>
              <dd>
                <code title={observation.source_revision}>
                  {observation.source_revision.slice(0, 12)}
                </code>
              </dd>
            </div>
            {compared && (
              <>
                <div>
                  <dt>{t('App definition')}</dt>
                  <dd>{matchLabel(observation.definition_matches)}</dd>
                </div>
                <div>
                  <dt>{t('Source commit')}</dt>
                  <dd>{matchLabel(observation.revision_matches)}</dd>
                </div>
                <div>
                  <dt>{t('Registered source revision')}</dt>
                  <dd>
                    <code
                      title={
                        observation.registered_source_revision ?? undefined
                      }
                    >
                      {observation.registered_source_revision?.slice(0, 12)}
                    </code>
                  </dd>
                </div>
              </>
            )}
          </dl>
          <p className="muted">
            {t(
              'Source changes after this check are not included. Check again after editing.',
            )}
          </p>
          {observation.state === 'collision' && (
            <p>
              {t(
                'Review the app ID and source connection. This result does not authorize changing the existing app.',
              )}
            </p>
          )}
          {compared && (
            <a href={`?view=apps&app=${encodeURIComponent(appId)}`}>
              {t('View app installations')}
            </a>
          )}
        </>
      )}
    </section>
  );
}
