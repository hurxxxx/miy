import { Button } from '@miy/ui';
import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { errorCopy, type Translate } from './i18n';
import type { components } from './api.generated';

/** Downloads public source metadata; it never calls a platform mutation. */
export function SourceRegistrationExport({
  projectId,
  t,
}: {
  projectId: string;
  t: Translate;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
      active.current = null;
    },
    [],
  );
  const download = async () => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    const deadline = window.setTimeout(() => controller.abort(), 30_000);
    setBusy(true);
    setError(null);
    try {
      const draft = await api<
        components['schemas']['SourceRegistrationDraftOut']
      >(
        `/workbench/projects/${encodeURIComponent(projectId)}/registration-draft`,
        undefined,
        'GET',
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const blob = new Blob([JSON.stringify(draft, null, 2) + '\n'], {
        type: 'application/json',
      });
      if (blob.size > 256 * 1024) throw new ApiError('app_source_invalid');
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'miy-app-registration.json';
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (reason) {
      if (!controller.signal.aborted || active.current === controller)
        setError(reason instanceof ApiError ? reason.code : 'request_failed');
    } finally {
      window.clearTimeout(deadline);
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  };
  return (
    <div className="stack">
      <Button
        variant="secondary"
        disabled={busy}
        onClick={() => void download()}
      >
        {t(
          busy ? 'Preparing registration draft' : 'Download registration draft',
        )}
      </Button>
      <p className="muted">
        {t(
          'Open this file in MIY App registration while signed in to MIY. Registration keeps the development installation inactive until its environment is ready.',
        )}
      </p>
      {error && (
        <p role="alert" className="danger">
          {t(errorCopy(error))}
        </p>
      )}
    </div>
  );
}
