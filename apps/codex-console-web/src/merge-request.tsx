import { Button } from '@miy/ui';
import { useEffect, useState } from 'react';
import { api, locked, type Detail } from './api';
import type { components } from './api.generated';
import type { Translate } from './i18n';

type Target = components['schemas']['MergeTarget'];
export type MergeRequestData = Omit<
  components['schemas']['MergeInput'],
  'operation_id' | 'model' | 'effort' | 'permissions'
>;
export function MergeRequest({
  task,
  linkId,
  refreshToken,
  busy,
  t,
  onMerge,
}: {
  task: Detail;
  linkId: string;
  refreshToken: string;
  busy: boolean;
  t: Translate;
  onMerge: (data: MergeRequestData) => Promise<boolean>;
}) {
  const [target, setTarget] = useState<Target | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api<Target>(
      `/tasks/${task.id}/merge-target?link_id=${encodeURIComponent(linkId)}`,
      undefined,
      'GET',
      controller.signal,
    )
      .then((next) => {
        if (!controller.signal.aborted) {
          setTarget(next);
          setUnavailable(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setTarget(null);
          setUnavailable(true);
        }
      });
    return () => controller.abort();
  }, [task.id, linkId, refreshToken]);
  return (
    <div className="merge-request stack">
      {target && (
        <>
          <strong>
            {t('Development target')}: {target.target_branch}
          </strong>
          <small className="workspace-path">{target.target_root}</small>
          <p className="context-note">
            {t(
              'Send Codex a merge request in this conversation, following repository instructions and the selected execution settings.',
            )}
          </p>
        </>
      )}
      <Button
        variant="secondary"
        disabled={
          busy ||
          locked(task) ||
          !target ||
          task.implementation_permissions?.length === 0
        }
        onClick={() =>
          target &&
          void onMerge({
            link_id: linkId,
            expected_head: target.source_head,
            expected_branch: target.source_branch,
            expected_target_head: target.target_head,
            expected_target_branch: target.target_branch,
          })
        }
      >
        {t('Request development merge')}
      </Button>
      {unavailable && (
        <small className="muted">
          {t(
            'Select a separate checkout in the configured development repository to request a merge.',
          )}
        </small>
      )}
    </div>
  );
}
