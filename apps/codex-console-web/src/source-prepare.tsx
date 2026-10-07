import { useEffect, useRef, useState } from 'react';
import { Button, Input } from '@miy/ui';
import { api, ApiError } from './api';
import type { components } from './api.generated';
import { errorCopy, type Translate } from './i18n';

type S = components['schemas'];
type Setup = S['SourceSetupOut'];
type Options = S['SourceSetupOptions'];
type InputBody = S['SourceSetupInput'];

function savedInput(setup: Setup): InputBody {
  return {
    operation_id: setup.operation_id,
    root_id: setup.root_id,
    template_id: setup.template_id,
    repository: setup.repository,
    expected_bundle_digest: setup.bundle_digest,
  };
}

/** A project preparation request never starts or elevates a Codex task. */
export function SourcePrepare({
  projectId,
  t,
  onPrepared,
}: {
  projectId: string;
  t: Translate;
  onPrepared: () => void;
}) {
  const path = `/workbench/projects/${encodeURIComponent(projectId)}/source-setup`;
  const [options, setOptions] = useState<Options | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [attempt, setAttempt] = useState<InputBody | null>(null);
  const [rootId, setRootId] = useState('');
  const [templateId, setTemplateId] = useState('basic');
  const [repository, setRepository] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readFailed, setReadFailed] = useState(false);
  const active = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const rejected = useRef(false);
  const prepared = useRef(onPrepared);
  prepared.current = onPrepared;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      active.current?.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const deadline = window.setTimeout(() => controller.abort(), 15000);
    let disposed = false;
    setLoading(true);
    setReadFailed(false);
    void Promise.all([
      api<Options>(
        '/workbench/source-setup/options',
        undefined,
        'GET',
        controller.signal,
      ),
      api<S['SourceSetupStatus']>(path, undefined, 'GET', controller.signal),
    ])
      .then(([available, result]) => {
        if (disposed || controller.signal.aborted) return;
        setOptions(available);
        setSetup(result.setup);
        setError(null);
        if (result.setup) {
          setAttempt(savedInput(result.setup));
          setRootId(result.setup.root_id);
          setTemplateId(result.setup.template_id);
          setRepository(result.setup.repository);
          if (result.setup.state === 'ready') prepared.current();
        } else {
          // A definite input rejection plus an absent durable intent permits
          // correction. An absent record alone cannot resolve a lost response.
          const canCorrect = rejected.current;
          if (canCorrect) {
            rejected.current = false;
            setAttempt(null);
          }
          setRootId((current) =>
            current &&
            (!canCorrect || available.roots.some((item) => item.id === current))
              ? current
              : available.roots[0]?.id || '',
          );
        }
      })
      .catch((reason) => {
        if (disposed) return;
        setReadFailed(true);
        setError(reason instanceof ApiError ? reason.code : 'request_failed');
      })
      .finally(() => {
        window.clearTimeout(deadline);
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
      window.clearTimeout(deadline);
      controller.abort();
    };
  }, [path, refresh]);

  const prepare = async () => {
    if (
      active.current ||
      loading ||
      readFailed ||
      !options ||
      setup?.state === 'conflict'
    )
      return;
    const starter = options.templates.find((item) => item.id === templateId);
    let input = attempt;
    if (!input) {
      if (!starter || !rootId || !repository) return;
      input = {
        operation_id: crypto.randomUUID(),
        root_id: rootId,
        template_id: starter.id,
        repository,
        expected_bundle_digest: starter.bundle_digest,
      };
    }
    // Retain the exact request even if its response is lost. The server also
    // records it before touching the source directory, so page reload can resume.
    setAttempt(input);
    const controller = new AbortController();
    active.current = controller;
    const deadline = window.setTimeout(() => controller.abort(), 30000);
    setBusy(true);
    setError(null);
    rejected.current = false;
    try {
      const result = await api<Setup>(path, input, 'POST', controller.signal);
      if (!mounted.current || controller.signal.aborted) return;
      setSetup(result);
      if (result.state === 'ready') prepared.current();
    } catch (reason) {
      if (mounted.current) {
        rejected.current =
          reason instanceof ApiError &&
          [
            'invalid_input',
            'app_setup_invalid',
            'app_setup_root_denied',
            'app_setup_bundle_changed',
            'app_setup_conflict',
          ].includes(reason.code);
        setReadFailed(true);
        setError(
          reason instanceof ApiError ? reason.code : 'source_setup_unknown',
        );
      }
    } finally {
      window.clearTimeout(deadline);
      if (active.current === controller) active.current = null;
      if (mounted.current) setBusy(false);
    }
  };

  const locked = busy || loading || !!attempt;
  const available = !!options?.roots.length && !!options.templates.length;
  return (
    <form
      className="wb-form"
      aria-label={t('Prepare app source')}
      onSubmit={(event) => {
        event.preventDefault();
        void prepare();
      }}
    >
      <h3>{t('Prepare app source')}</h3>
      <p className="muted">
        {t(
          'Create a starter app in an approved folder and connect its source to this project.',
        )}
      </p>
      {loading && <p role="status">{t('Loading source preparation')}</p>}
      {error && (
        <p role="alert" className="danger">
          {t(errorCopy(error))}
        </p>
      )}
      {!loading && options && !available && !setup && (
        <p>
          {t(
            'An administrator must configure a folder for creating apps before source preparation is available.',
          )}
        </p>
      )}
      {setup?.state === 'ready' ? (
        <div className="stack" role="status">
          <strong>{t('App source prepared')}</strong>
          <p>
            {t(
              'Source is connected. Check the app execution environment before starting development.',
            )}
          </p>
          <code style={{ overflowWrap: 'anywhere' }}>{setup.source_root}</code>
        </div>
      ) : (
        (available || setup) && (
          <>
            <label>
              {t('Starter template')}
              <select
                value={templateId}
                disabled={locked}
                onChange={(event) => setTemplateId(event.target.value)}
              >
                {options?.templates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {t(
                      item.id === 'private-notes'
                        ? 'App with private notes'
                        : 'Web and API app',
                    )}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t('App creation folder')}
              <select
                value={rootId}
                disabled={locked}
                required
                onChange={(event) => setRootId(event.target.value)}
              >
                {options?.roots.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t('App repository URL')}
              <Input
                type="url"
                required
                maxLength={500}
                value={repository}
                disabled={locked}
                onChange={(event) => setRepository(event.target.value)}
              />
            </label>
            <p className="muted">
              {t(
                'Use the HTTPS address of the repository intended for this app. This step creates the local source only.',
              )}
            </p>
            {setup?.state === 'preparing' && (
              <p role="status">
                {t(
                  'Source preparation is pending. Check its status before continuing.',
                )}
              </p>
            )}
            {setup?.state === 'failed' && (
              <p role="alert">
                {t(
                  'Source preparation stopped. Continue the same request to resume.',
                )}
              </p>
            )}
            {setup?.state === 'conflict' && (
              <p role="alert">
                {t(
                  'The source folder needs review. Existing files have been preserved.',
                )}
              </p>
            )}
            {setup?.failure_code && (
              <p className="danger">{t(errorCopy(setup.failure_code))}</p>
            )}
            <Button
              type="submit"
              disabled={
                busy ||
                loading ||
                readFailed ||
                !available ||
                setup?.state === 'conflict'
              }
            >
              {t(
                busy
                  ? 'Preparing app source'
                  : attempt
                    ? 'Continue source preparation'
                    : 'Prepare app source',
              )}
            </Button>
          </>
        )
      )}
      <Button
        type="button"
        variant="ghost"
        disabled={busy || loading}
        onClick={() => setRefresh((value) => value + 1)}
      >
        {t('Check preparation status')}
      </Button>
    </form>
  );
}
