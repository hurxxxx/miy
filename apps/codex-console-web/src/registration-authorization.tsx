import { Button, Input } from '@miy/ui';
import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Task } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';
import {
  checkedRegistrationStatus,
  checkedAuthorizationUrl,
} from './registration-authorization-contract';

type Status = components['schemas']['Status'];
type Start = components['schemas']['AuthorizationStart'];
const states: Record<Status['authorization_state'], Copy> = {
  required: 'Registration authorization required.',
  pending: 'Waiting for MIY owner authorization.',
  exchanging: 'Confirming registration authorization.',
  ready: 'Registration authorization connected.',
  expired:
    'Registration authorization expired. Reconnect to inspect the same operation.',
  failed: 'Registration authorization was not confirmed. Reconnect explicitly.',
  other_session:
    'This task belongs to another login session. Reconnect explicitly.',
};

/** Credentials and approval codes never enter this component. */
export function RegistrationAuthorization({
  task,
  t,
}: {
  task: Pick<Task, 'id' | 'status'>;
  t: Translate;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [origin, setOrigin] = useState('');
  const [approvalUrl, setApprovalUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expiryTick, setExpiryTick] = useState(0);
  const active = useRef<AbortController | null>(null);
  const taskId = task.id;
  const taskBusy = ['starting', 'running', 'waiting', 'uncertain'].includes(
    task.status,
  );
  const path = `/tasks/${encodeURIComponent(taskId)}/registration`;

  useEffect(() => {
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    const timeout = window.setTimeout(() => {
      controller.abort();
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
        setError('request_timeout');
      }
    }, 30_000);
    void api<Status>(path, undefined, 'GET', controller.signal)
      .then((value) => {
        if (!controller.signal.aborted && active.current === controller) {
          const checked = checkedRegistrationStatus(value, taskId);
          setStatus(checked);
          setOrigin(checked.policy?.origin ?? '');
        }
      })
      .catch((reason: unknown) => {
        if (active.current === controller)
          setError(reason instanceof ApiError ? reason.code : 'request_failed');
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (active.current === controller) {
          active.current = null;
          setBusy(false);
        }
      });
    return () => {
      active.current = null;
      controller.abort();
      window.clearTimeout(timeout);
    };
    // The parent keys this component by Task; each effect owns one read.
  }, [path]);
  useEffect(
    () => () => {
      active.current?.abort();
      active.current = null;
    },
    [],
  );
  const expires = status?.expires_at ? Date.parse(status.expires_at) : null;
  const expired = expires !== null && expires <= Date.now();
  useEffect(() => {
    if (expires === null || expired) return;
    const timeout = window.setTimeout(
      () => setExpiryTick((tick) => tick + 1),
      Math.min(2_147_483_647, Math.max(1, Math.ceil(expires - Date.now()) + 1)),
    );
    return () => window.clearTimeout(timeout);
  }, [expires, expired, expiryTick]);

  const request = async (kind: 'read' | 'authorize' | 'receipt') => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(null);
    setApprovalUrl(null);
    const timeout = window.setTimeout(() => {
      controller.abort();
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
        setError('request_timeout');
      }
    }, 30_000);
    try {
      const value = await api<Status | Start>(
        path + (kind === 'read' ? '' : `/${kind}`),
        kind === 'authorize' ? { origin } : undefined,
        kind === 'read' ? 'GET' : 'POST',
        controller.signal,
      );
      if (active.current !== controller || controller.signal.aborted) return;
      const checked = checkedRegistrationStatus(
        'status' in value ? value.status : value,
        taskId,
        status,
      );
      setStatus(checked);
      setOrigin(checked.policy?.origin ?? origin);
      if ('authorization_url' in value) {
        setApprovalUrl(
          checkedAuthorizationUrl(value.authorization_url, checked, status),
        );
      }
    } catch (reason) {
      if (active.current === controller)
        setError(reason instanceof ApiError ? reason.code : 'request_failed');
    } finally {
      window.clearTimeout(timeout);
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  };
  return (
    <section className="panel stack" aria-label={t('First app registration')}>
      <h2>{t('First app registration')}</h2>
      <p className="muted">
        {t(
          'This task uses the selected app source. Save and review its changes before initial registration.',
        )}
      </p>
      <p className="muted">
        {t(
          'Only this new registration task receives the registration tool. MIY owner authorization and implementation approval are both required.',
        )}
      </p>
      {status && (
        <>
          <p role="status">
            {t(
              states[
                expired && status.authorization_state !== 'other_session'
                  ? 'expired'
                  : status.authorization_state
              ],
            )}
          </p>
          <p className="muted">
            {t('Registration operation')}: <code>{status.operation_id}</code>
          </p>
          {status.expires_at && (
            <p>
              {t('Authorization expires at')}:{' '}
              <time dateTime={status.expires_at}>
                {new Date(status.expires_at).toLocaleString(t.locale)}
              </time>
            </p>
          )}
          {status.state === 'unknown' && (
            <p role="status">
              {t(
                'The registration response is unknown. Inspect this same operation; it will not be submitted automatically.',
              )}
            </p>
          )}
          {status.receipt && (
            <div className="stack">
              <p>
                {t(
                  'Historical registration receipt. The development installation was created inactive; this does not confirm current source, activation or deployment.',
                )}
              </p>
              <code>{status.receipt.source_revision}</code>
              <a
                href={`?view=apps&app=${encodeURIComponent(status.receipt.app_id)}`}
              >
                {t('View app installations')}
              </a>
              {status.authorization_origin && (
                <a
                  href={`${status.authorization_origin}/apps/${encodeURIComponent(status.receipt.app_id)}/installed/${encodeURIComponent(status.receipt.installation_id)}/setup`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t('Configure my development preview in MIY')}
                </a>
              )}
            </div>
          )}
        </>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void request('authorize');
        }}
        className="stack"
      >
        <label>
          {t('Development app origin')}
          <Input
            required
            type="url"
            value={origin}
            disabled={busy || taskBusy || !!status?.source_revision}
            onChange={(event) => setOrigin(event.target.value)}
            placeholder="https://preview.example.com"
          />
        </label>
        <div className="actions">
          <Button
            type="submit"
            disabled={busy || taskBusy || status?.enabled === false}
          >
            {t('Connect registration authorization')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => void request('read')}
          >
            {t('Refresh authorization status')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={
              busy || expired || status?.authorization_state !== 'ready'
            }
            onClick={() => void request('receipt')}
          >
            {t('Inspect the same registration operation')}
          </Button>
        </div>
      </form>
      {approvalUrl && (
        <a href={approvalUrl} target="_blank" rel="noopener noreferrer">
          {t('Approve in MIY')}
        </a>
      )}
      <p className="muted">
        {t(
          'Authorize once in MIY, then refresh this task. Registration does not enable the app or deploy it. The JSON export remains available in Studio.',
        )}
      </p>
      {error && (
        <p role="alert" className="danger">
          {t(errorCopy(error))}
        </p>
      )}
    </section>
  );
}
