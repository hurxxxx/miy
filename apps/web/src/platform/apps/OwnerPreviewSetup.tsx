import { Button, useFeedback } from '@miy/ui';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { apiFetchJson, ApiRequestError } from '@/src/platform/api/client';
import { useAuth } from '@/src/platform/auth/auth-provider';
import {
  ownerPreviewApiPath,
  parseOwnerPreview,
  validOwnerPreviewTarget,
  type OwnerPreview,
  type OwnerPreviewInput,
} from './owner-preview';

export default function OwnerPreviewSetup() {
  const { token, user } = useAuth();
  const { appId = '', installationId = '' } = useParams();
  const latest = useRef({
    token,
    userId: user?.id,
    appId,
    installationId,
    epoch: 0,
  });
  if (
    latest.current.token !== token ||
    latest.current.userId !== user?.id ||
    latest.current.appId !== appId ||
    latest.current.installationId !== installationId
  )
    latest.current = {
      token,
      userId: user?.id,
      appId,
      installationId,
      epoch: latest.current.epoch + 1,
    };
  const epoch = latest.current.epoch;
  return token && user ? (
    <PreviewForm
      key={epoch}
      token={token}
      userId={user.id}
      appId={appId}
      installationId={installationId}
      isCurrent={() => latest.current.epoch === epoch}
    />
  ) : null;
}

function PreviewForm({
  token,
  userId,
  appId,
  installationId,
  isCurrent,
}: {
  token: string;
  userId: string;
  appId: string;
  installationId: string;
  isCurrent: () => boolean;
}) {
  const { t } = useTranslation('shell');
  const copy = (key: string) => t(`independentApps.previewSetup.${key}`);
  const feedback = useFeedback();
  const [snapshot, setSnapshot] = useState<OwnerPreview | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [grants, setGrants] = useState<OwnerPreview['granted_permissions']>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [mustRefresh, setMustRefresh] = useState(false);
  const active = useRef(false);
  const pending = useRef<AbortController | null>(null);
  const uncertain = useRef(false);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      pending.current?.abort();
      pending.current = null;
    };
  }, []);

  const current = () => active.current && isCurrent();
  const valid = validOwnerPreviewTarget(appId, installationId);
  const request = async (method: 'GET' | 'PATCH') => {
    if (pending.current || !current() || !valid) return;
    if (method === 'PATCH' && (!snapshot?.can_configure || mustRefresh)) return;
    const controller = new AbortController();
    pending.current = controller;
    const currentRequest = () => current() && pending.current === controller;
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(30_000),
    ]);
    let rejectCancelled: (reason: unknown) => void = () => undefined;
    const cancelled = () => rejectCancelled(signal.reason);
    const cancellation = new Promise<never>((_, reject) => {
      rejectCancelled = reject;
      signal.addEventListener('abort', cancelled, { once: true });
    });
    const priorUnknown = uncertain.current;
    const previous = snapshot;
    setBusy(true);
    setMessage(null);
    try {
      const body: OwnerPreviewInput | undefined =
        method === 'PATCH' && previous
          ? {
              expected_generation: previous.generation,
              expected_definition_digest: previous.definition_digest,
              expected_source_revision: previous.source_revision,
              enabled,
              granted_permissions: [...grants].sort(),
            }
          : undefined;
      const response = await Promise.race([
        apiFetchJson<unknown>(
          ownerPreviewApiPath(appId, installationId),
          token,
          {
            method,
            signal,
            ...(body ? { body: JSON.stringify(body) } : {}),
          },
        ),
        cancellation,
      ]);
      if (!currentRequest()) return;
      if (signal.aborted) throw signal.reason;
      const next = parseOwnerPreview(response, {
        appId,
        installationId,
        userId,
      });
      const changed =
        body &&
        previous &&
        (body.enabled !== previous.enabled ||
          body.granted_permissions.join(',') !==
            [...previous.granted_permissions].sort().join(','));
      if (
        body &&
        (next.definition_digest !== body.expected_definition_digest ||
          next.source_revision !== body.expected_source_revision ||
          next.origin !== previous?.origin ||
          next.generation !== body.expected_generation + (changed ? 1 : 0) ||
          next.enabled !== body.enabled ||
          [...next.granted_permissions].sort().join(',') !==
            body.granted_permissions.join(','))
      )
        throw new Error('preview-response-mismatch');
      setSnapshot(next);
      setEnabled(next.enabled);
      setGrants(next.granted_permissions);
      setMustRefresh(false);
      uncertain.current = false;
      if (method === 'PATCH') feedback.success(copy('saved'));
      else if (priorUnknown) setMessage('observed');
    } catch (error) {
      if (!currentRequest()) return;
      if (method === 'PATCH') {
        setMustRefresh(true);
        const rejected =
          error instanceof ApiRequestError &&
          [400, 401, 403, 404, 409, 422].includes(error.status);
        uncertain.current = !rejected;
        setMessage(rejected ? 'changed' : 'unknown');
      } else {
        setSnapshot(null);
        setMessage('unavailable');
      }
    } finally {
      signal.removeEventListener('abort', cancelled);
      if (currentRequest()) setBusy(false);
      if (pending.current === controller) pending.current = null;
    }
  };

  const initialRead = useRef(request);
  useEffect(() => {
    void initialRead.current('GET');
  }, []);
  const same =
    !!snapshot &&
    enabled === snapshot.enabled &&
    [...grants].sort().join(',') ===
      [...snapshot.granted_permissions].sort().join(',');
  const locked = busy || mustRefresh || !snapshot?.can_configure;
  const permissionCopy = {
    'identity:read': 'identity',
    'data:read': 'dataRead',
    'data:write': 'dataWrite',
    'files:read-selected': 'selectedFileRead',
  } as const satisfies Record<
    OwnerPreview['requested_permissions'][number],
    string
  >;
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-5 overflow-auto p-5 text-app-ink">
      <h1 className="app-text-title-lg">{copy('title')}</h1>
      <p className="app-text-body text-app-ink/70">{copy('description')}</p>
      {!valid && <p role="alert">{copy('unavailable')}</p>}
      {busy && <p role="status">{copy('working')}</p>}
      {message && (
        <p role={message === 'observed' ? 'status' : 'alert'}>
          {copy(message)}
        </p>
      )}
      {snapshot && (
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            void request('PATCH');
          }}
        >
          <dl className="space-y-1 break-words border-b border-app-border pb-4">
            <dt className="app-text-caption text-app-ink/60">{copy('app')}</dt>
            <dd>{snapshot.display_name}</dd>
            <dt className="app-text-caption text-app-ink/60">
              {copy('origin')}
            </dt>
            <dd>{snapshot.origin}</dd>
          </dl>
          {!snapshot.can_configure && (
            <p role="status">
              {copy(
                snapshot.unavailable_reason === 'company_disabled'
                  ? 'companyDisabled'
                  : snapshot.unavailable_reason ===
                        'origin_configuration_required' ||
                      snapshot.unavailable_reason === 'invalid_origin'
                    ? 'configurationRequired'
                    : 'locked',
              )}
            </p>
          )}
          <fieldset disabled={locked} className="space-y-4">
            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              {copy('enabled')}
            </label>
            <fieldset className="space-y-2">
              <legend className="app-text-title-sm mb-2">
                {copy('permissions')}
              </legend>
              {snapshot.requested_permissions.length === 0 && (
                <p>{copy('none')}</p>
              )}
              {snapshot.requested_permissions.map((permission) => (
                <label key={permission} className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={grants.includes(permission)}
                    onChange={(event) =>
                      setGrants(
                        event.target.checked
                          ? [...grants, permission]
                          : grants.filter((item) => item !== permission),
                      )
                    }
                  />
                  {copy(permissionCopy[permission])}
                </label>
              ))}
            </fieldset>
            <p className="app-text-body-sm text-app-ink/60">{copy('limits')}</p>
            {snapshot.runtime_profile === 'web-api-postgres-v1' && (
              <p className="app-text-body-sm text-app-ink/60">
                {copy('dataLimits')}
              </p>
            )}
            <Button type="submit" disabled={locked || same}>
              {copy('save')}
            </Button>
          </fieldset>
        </form>
      )}
      <div className="flex flex-wrap items-center gap-4">
        <Button
          variant="secondary"
          disabled={busy || !valid}
          onClick={() => void request('GET')}
        >
          {copy('refresh')}
        </Button>
        <Link className="text-app-accent" to="/">
          {copy('back')}
        </Link>
      </div>
    </main>
  );
}
