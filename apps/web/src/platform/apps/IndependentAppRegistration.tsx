import { Button, Input } from '@miy/ui';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';

import { apiFetchJson, ApiRequestError } from '@/src/platform/api/client';
import type {
  ApiJsonRequestBody,
  ApiJsonResponse,
} from '@/src/platform/api/types';
import { useAuth } from '@/src/platform/auth/auth-provider';
import { ownerPreviewSettingsPath } from './owner-preview';
import { independentPermissionCopy } from './independent-app-permissions';
import {
  parseRegistrationDraft,
  parseRegistrationReceipt,
  registrationOperation,
  REGISTRATION_FILE_LIMIT,
  type RegistrationDraft,
} from './independent-app-registration';

type Submission = ApiJsonRequestBody<
  '/api/v1/independent-apps/bootstrap',
  'post'
>;
type Receipt = ApiJsonResponse<'/api/v1/independent-apps/bootstrap', 'post'>;

export default function IndependentAppRegistration() {
  const { token, user } = useAuth();
  const [query, setQuery] = useSearchParams();
  const operation = registrationOperation(query.get('operation'));
  const [route, setRoute] = useState({ operation, generation: 0 });
  const ownedNavigation = useRef<string | null>(null);
  const localChange =
    ownedNavigation.current === operation && operation !== null;
  useEffect(() => {
    if (route.operation === operation) return;
    const local = ownedNavigation.current === operation && operation !== null;
    ownedNavigation.current = null;
    setRoute((current) => ({
      operation,
      generation: current.generation + (local ? 0 : 1),
    }));
  }, [operation, route.operation]);
  const selectOperation = (id: string) => {
    ownedNavigation.current = id;
    setQuery({ operation: id }, { replace: true });
  };
  // Account/session changes discard unsubmitted contents and abort pending reads.
  // External history/query changes also unmount stale contents immediately. Our
  // own submitted operation updates the URL while keeping its in-flight request.
  return token && user && (route.operation === operation || localChange) ? (
    <RegistrationForm
      key={`${user.id}:${token}:${route.generation}`}
      token={token}
      selectOperation={selectOperation}
    />
  ) : null;
}

function RegistrationForm({
  token,
  selectOperation,
}: {
  token: string;
  selectOperation: (id: string) => void;
}) {
  const { t } = useTranslation('shell');
  const copy = (key: string) => t(`independentApps.registration.${key}`);
  const [query] = useSearchParams();
  const operation = registrationOperation(query.get('operation'));
  const [draft, setDraft] = useState<RegistrationDraft | null>(null);
  const [origin, setOrigin] = useState('');
  const [permissions, setPermissions] = useState<string[]>([]);
  const [attempt, setAttempt] = useState<Submission | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState<{
    key: 'notFound' | 'checkFailed' | 'invalidFile' | 'rejected' | 'unknown';
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const fileVersion = useRef(0);
  const lifetime = useRef(new AbortController());

  const request = useCallback(
    async <T,>(
      path: string,
      signal: AbortSignal,
      body?: Submission,
    ): Promise<T> =>
      apiFetchJson<T>(path, token, {
        method: body ? 'POST' : 'GET',
        ...(body ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.any([signal, AbortSignal.timeout(30_000)]),
      }),
    [token],
  );

  const check = useCallback(
    async (id: string) => {
      if (pending.current) return;
      const signal = lifetime.current.signal;
      pending.current = true;
      setBusy(true);
      setError(null);
      try {
        const value = await request<unknown>(
          `/api/v1/independent-apps/bootstrap/${id}`,
          signal,
        );
        if (!signal.aborted)
          setReceipt(parseRegistrationReceipt(value, { operation_id: id }));
      } catch (reason) {
        if (!signal.aborted)
          setError({
            key:
              reason instanceof ApiRequestError && reason.status === 404
                ? 'notFound'
                : 'checkFailed',
          });
      } finally {
        if (!signal.aborted) {
          pending.current = false;
          setBusy(false);
        }
      }
    },
    [request],
  );
  // Refreshing a page only reads its receipt; it never repeats the mutation.
  const initialOperation = useRef(operation);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    pending.current = false;
    if (initialOperation.current) void check(initialOperation.current);
    return () => {
      controller.abort();
      fileVersion.current++;
    };
  }, [check]);

  const load = async (file?: File) => {
    if (!file || pending.current || attempt || receipt) return;
    const version = ++fileVersion.current;
    setError(null);
    setDraft(null);
    setPermissions([]);
    try {
      if (file.size > REGISTRATION_FILE_LIMIT) throw new TypeError();
      const value = parseRegistrationDraft(await file.text());
      if (version === fileVersion.current && !lifetime.current.signal.aborted)
        setDraft(value);
    } catch {
      if (version === fileVersion.current && !lifetime.current.signal.aborted)
        setError({ key: 'invalidFile' });
    }
  };
  const submit = async () => {
    if (pending.current || !draft || receipt) return;
    const signal = lifetime.current.signal;
    const id = attempt?.operation_id ?? operation ?? crypto.randomUUID();
    const body: Submission = attempt ?? {
      operation_id: id,
      definition: draft.definition,
      source_revision: draft.source_revision,
      origin,
      granted_permissions: permissions as Submission['granted_permissions'],
    };
    pending.current = true;
    setAttempt(body);
    // The URL carries only an opaque receipt ID, never the draft or a bearer token.
    selectOperation(id);
    setBusy(true);
    setError(null);
    try {
      const value = await request<unknown>(
        '/api/v1/independent-apps/bootstrap',
        signal,
        body,
      );
      if (!signal.aborted)
        setReceipt(
          parseRegistrationReceipt(value, {
            operation_id: id,
            app_id: body.definition.app_id,
            source_revision: body.source_revision,
            definition_digest: draft.definition_digest,
          }),
        );
    } catch (reason) {
      if (!signal.aborted) {
        const rejected =
          reason instanceof ApiRequestError &&
          [400, 403, 409, 422].includes(reason.status);
        setError({ key: rejected ? 'rejected' : 'unknown' });
        // Keep the URL operation identity even when correcting a definite rejection.
        if (rejected) setAttempt(null);
      }
    } finally {
      if (!signal.aborted) {
        pending.current = false;
        setBusy(false);
      }
    }
  };
  const locked = busy || !!attempt || !!receipt;
  return (
    <div className="mx-auto w-full max-w-2xl space-y-5 p-6 text-app-ink">
      <h1 className="app-text-title-xl">{copy('title')}</h1>
      <p className="app-text-body text-app-ink/70">{copy('description')}</p>
      {error && (
        <p role="alert" className="text-app-danger">
          {copy(error.key)}
        </p>
      )}
      {busy && <p role="status">{copy('working')}</p>}
      {receipt ? (
        <section className="space-y-3" aria-label={copy('receipt')}>
          <h2 className="app-text-title-md">{copy('registered')}</h2>
          <p>{copy('pendingSetup')}</p>
          <Link
            className="text-app-accent"
            to={ownerPreviewSettingsPath(
              receipt.app_id,
              receipt.installation_id,
            )}
          >
            {t('independentApps.previewSetup.title')}
          </Link>
          <dl className="break-words">
            <dt>{copy('appId')}</dt>
            <dd>{receipt.app_id}</dd>
            <dt>{copy('installation')}</dt>
            <dd>{receipt.installation_id}</dd>
            <dt>{copy('revision')}</dt>
            <dd>{receipt.source_revision}</dd>
          </dl>
        </section>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="block space-y-2">
            <span>{copy('file')}</span>
            <input
              type="file"
              accept=".json,application/json"
              disabled={locked}
              onChange={(event) => void load(event.target.files?.[0])}
            />
          </label>
          {draft && (
            <dl className="break-words rounded-xl border border-app-border p-4">
              <dt>{copy('name')}</dt>
              <dd>{draft.definition.display.name}</dd>
              <dt>{copy('appId')}</dt>
              <dd>{draft.app_id}</dd>
              <dt>{copy('repository')}</dt>
              <dd>{draft.definition.source.repository}</dd>
              <dt>{copy('revision')}</dt>
              <dd>{draft.source_revision}</dd>
            </dl>
          )}
          <label className="block space-y-2">
            <span>{copy('origin')}</span>
            <Input
              type="url"
              required
              maxLength={300}
              aria-describedby="registration-origin-help"
              value={origin}
              disabled={locked}
              onChange={(event) => setOrigin(event.target.value)}
            />
          </label>
          <p
            id="registration-origin-help"
            className="app-text-body-sm text-app-ink/70"
          >
            {copy('originHelp')}
          </p>
          {!!draft?.definition.requested_permissions?.length && (
            <fieldset disabled={locked} className="space-y-2">
              <legend>{copy('permissions')}</legend>
              {draft.definition.requested_permissions.map((permission) => (
                <label key={permission} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={permissions.includes(permission)}
                    onChange={(event) =>
                      setPermissions((current) =>
                        event.target.checked
                          ? [...current, permission]
                          : current.filter((item) => item !== permission),
                      )
                    }
                  />
                  {copy(independentPermissionCopy[permission])}
                </label>
              ))}
            </fieldset>
          )}
          <Button type="submit" disabled={busy || !draft}>
            {copy(attempt ? 'retry' : 'submit')}
          </Button>
        </form>
      )}
      {operation && !receipt && (
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => void check(operation)}
        >
          {copy('check')}
        </Button>
      )}
      <Link to="/" className="block text-app-accent">
        {copy('back')}
      </Link>
    </div>
  );
}
