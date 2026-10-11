import { Button } from '@miy/ui';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';

import { apiFetchJson, ApiRequestError } from '@/src/platform/api/client';
import { useAuth } from '@/src/platform/auth/auth-provider';
import { independentPermissionCopy } from './independent-app-permissions';
import {
  parseRegistrationAuthorizationQuery,
  parseRegistrationAuthorizationResponse,
  postRegistrationAuthorization,
  REGISTRATION_AUTHORIZATION_API,
  type RegistrationAuthorizationInput,
} from './registration-authorization';

export default function RegistrationAuthorization() {
  const { token, user } = useAuth();
  const { search } = useLocation();
  const latest = useRef({ token, userId: user?.id, search });
  latest.current = { token, userId: user?.id, search };
  return token && user ? (
    <AuthorizationConsent
      key={`${user.id}:${token}:${search}`}
      token={token}
      userId={user.id}
      accountName={user.email}
      search={search}
      isCurrent={() =>
        latest.current.token === token &&
        latest.current.userId === user.id &&
        latest.current.search === search
      }
    />
  ) : null;
}

function AuthorizationConsent({
  token,
  userId,
  accountName,
  search,
  isCurrent,
}: {
  token: string;
  userId: string;
  accountName: string;
  search: string;
  isCurrent: () => boolean;
}) {
  const { t } = useTranslation('shell');
  const copy = (key: string) => t(`independentApps.authorization.${key}`);
  const [state, setState] = useState<
    | 'ready'
    | 'submitting'
    | 'returning'
    | 'unknown'
    | 'rejected'
    | 'unsupported'
  >('ready');
  const lifetime = useRef(new AbortController());
  const submitted = useRef(false);
  const cleanupReturn = useRef<(() => void) | null>(null);
  let proposal: RegistrationAuthorizationInput | null = null;
  try {
    proposal = parseRegistrationAuthorizationQuery(search);
  } catch {
    // The untrusted query and server errors are never reflected into the page.
  }
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => {
      controller.abort();
      cleanupReturn.current?.();
    };
  }, []);
  const authorize = async () => {
    if (!proposal || submitted.current || !isCurrent()) return;
    const expected = proposal;
    const signal = AbortSignal.any([
      lifetime.current.signal,
      AbortSignal.timeout(30_000),
    ]);
    submitted.current = true;
    setState('submitting');
    const cancelled = () => rejectCancellation(signal.reason);
    let rejectCancellation: (reason: unknown) => void = () => undefined;
    const cancellation = new Promise<never>((_, reject) => {
      rejectCancellation = reject;
      signal.addEventListener('abort', cancelled, { once: true });
    });
    try {
      const value = await Promise.race([
        apiFetchJson<unknown>(REGISTRATION_AUTHORIZATION_API, token, {
          method: 'POST',
          body: JSON.stringify(expected),
          signal,
        }),
        cancellation,
      ]);
      if (lifetime.current.signal.aborted || !isCurrent()) return;
      if (signal.aborted) throw signal.reason;
      const response = parseRegistrationAuthorizationResponse(
        value,
        expected,
        userId,
      );
      setState('returning');
      const releaseForm = postRegistrationAuthorization(response);
      const returnDeadline = window.setTimeout(() => {
        releaseForm();
        if (!lifetime.current.signal.aborted && isCurrent())
          setState('unknown');
      }, 15_000);
      cleanupReturn.current = () => {
        window.clearTimeout(returnDeadline);
        releaseForm();
      };
    } catch (reason) {
      if (lifetime.current.signal.aborted || !isCurrent()) return;
      setState(
        reason instanceof ApiRequestError && [404, 405].includes(reason.status)
          ? 'unsupported'
          : reason instanceof ApiRequestError &&
              [400, 401, 403, 409, 422].includes(reason.status)
            ? 'rejected'
            : 'unknown',
      );
    } finally {
      signal.removeEventListener('abort', cancelled);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-5 overflow-auto p-5">
      <h1 className="app-text-title-lg">{copy('title')}</h1>
      <p className="app-text-body text-app-ink/70">{copy('description')}</p>
      {!proposal ? (
        <p role="alert">{copy('invalid')}</p>
      ) : (
        <>
          <dl className="grid gap-3 rounded-md border border-app-border bg-app-surface p-4 app-text-body">
            {[
              ['account', accountName],
              ['appId', proposal.policy.app_id],
              ['workbench', proposal.audience],
              ['origin', proposal.policy.origin],
              [
                'profile',
                copy(
                  proposal.policy.runtime_profile === 'web-api-postgres-v1'
                    ? 'dataApp'
                    : 'webApp',
                ),
              ],
              [
                'requestedPermissions',
                proposal.policy.requested_permissions
                  .map((permission) =>
                    t(
                      `independentApps.registration.${independentPermissionCopy[permission]}`,
                    ),
                  )
                  .join(', ') || copy('none'),
              ],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-app-ink/60">{copy(label)}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="app-text-body">{copy('limits')}</p>
          <p className="app-text-body text-app-ink/70">{copy('expiry')}</p>
          {state !== 'ready' ? (
            <p
              role={
                ['unknown', 'rejected', 'unsupported'].includes(state)
                  ? 'alert'
                  : 'status'
              }
            >
              {copy(state)}
            </p>
          ) : null}
          <Button disabled={state !== 'ready'} onClick={() => void authorize()}>
            {copy('approve')}
          </Button>
        </>
      )}
      <Link
        className="app-text-body text-app-accent underline"
        to="/apps/register"
      >
        {copy('manual')}
      </Link>
      <Link className="app-text-body text-app-accent underline" to="/">
        {copy('cancel')}
      </Link>
    </main>
  );
}
